#!/usr/bin/env bash
# Faro — instalação em servidor Linux (systemd + nginx)
#
# Uso (como root):
#   ./deploy/deploy.sh install     # instala: código, venv, usuário, timer do systemd, nginx; gera a 1ª página
#   ./deploy/deploy.sh update      # baixa a versão nova do repositório, reaplica tudo e gera a página
#   ./deploy/deploy.sh run         # gera a página agora (sem esperar o timer)
#   ./deploy/deploy.sh status      # timer, última execução, idade da página, nginx
#   ./deploy/deploy.sh uninstall   # remove timer, nginx, usuário, página e cache (não mexe em outros sites)
#
# Sem clonar antes:
#   curl -fsSL https://raw.githubusercontent.com/brunomrtns/faro/main/deploy/deploy.sh | sudo bash -s install
#
# Nada aqui é específico de máquina: nenhum IP, senha ou nome de host. Tudo tem padrão
# e pode ser trocado por variável de ambiente, por exemplo:
#   sudo FARO_URL_PATH=/radar FARO_AGENDA='*:0/30' ./deploy/deploy.sh install
#
#   FARO_REPO        repositório git                     (padrão: https://github.com/brunomrtns/faro.git)
#   FARO_BRANCH      branch                              (padrão: main)
#   FARO_DIR         onde o código fica                  (padrão: /opt/faro)
#   FARO_WWW         pasta da página gerada              (padrão: /var/lib/faro/www)
#   FARO_USER        usuário de sistema que roda o Faro  (padrão: faro)
#   FARO_URL_PATH    caminho no nginx                    (padrão: /faro)
#   FARO_AGENDA      OnCalendar do timer do systemd      (padrão: hourly)
#   FARO_ARGS        argumentos extras do faro.py        (ex.: "--max 30 --dias 14")
#   FARO_NGINX_SITE  arquivo do site nginx que recebe o include
#                    (padrão: o site que tem "default_server"; "nenhum" = não mexe no nginx)

set -euo pipefail

FARO_REPO="${FARO_REPO:-https://github.com/brunomrtns/faro.git}"
FARO_BRANCH="${FARO_BRANCH:-main}"
FARO_DIR="${FARO_DIR:-/opt/faro}"
FARO_WWW="${FARO_WWW:-/var/lib/faro/www}"
FARO_USER="${FARO_USER:-faro}"
FARO_URL_PATH="${FARO_URL_PATH:-/faro}"
FARO_AGENDA="${FARO_AGENDA:-hourly}"
FARO_ARGS="${FARO_ARGS:-}"
FARO_NGINX_SITE="${FARO_NGINX_SITE:-}"

FARO_URL_PATH="/${FARO_URL_PATH#/}"; FARO_URL_PATH="${FARO_URL_PATH%/}"
SERVICO="faro"
UNIT_SERVICE="/etc/systemd/system/${SERVICO}.service"
UNIT_TIMER="/etc/systemd/system/${SERVICO}.timer"
CACHE_DIR="/var/cache/faro"        # criada pelo systemd (CacheDirectory=faro)
SNIPPET="/etc/nginx/snippets/faro.conf"
MARCA="# faro"                     # marca a linha de include que este script coloca e tira
LINHA_INCLUDE="include snippets/faro.conf;  ${MARCA}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[AVISO]${NC} $*"; }
err()  { echo -e "${RED}[ERRO]${NC} $*" >&2; }

preflight() {
    if [[ "$(id -u)" -ne 0 ]]; then
        err "Rode como root (sudo)."
        exit 1
    fi
    command -v systemctl >/dev/null || { err "Precisa de systemd."; exit 1; }
}

# ---------------------------------------------------------------------------
# Dependências, usuário e código
# ---------------------------------------------------------------------------

instalar_dependencias() {
    local faltando=()
    command -v git >/dev/null || faltando+=(git)
    command -v python3 >/dev/null || faltando+=(python3)
    python3 -c 'import ensurepip' 2>/dev/null || faltando+=(python3-venv)
    if [[ ${#faltando[@]} -eq 0 ]]; then
        ok "Dependências do sistema já instaladas"
        return
    fi
    info "Instalando: ${faltando[*]}"
    if command -v apt-get >/dev/null; then
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${faltando[@]}"
    elif command -v dnf >/dev/null; then
        dnf install -y -q git python3   # no RHEL/Rocky o venv já vem com o python3
    else
        err "Instale manualmente: ${faltando[*]}"
        exit 1
    fi
    ok "Dependências instaladas"
}

criar_usuario() {
    if id "$FARO_USER" &>/dev/null; then
        ok "Usuário $FARO_USER já existe"
        return
    fi
    useradd --system --home-dir /var/lib/faro --no-create-home --shell /usr/sbin/nologin "$FARO_USER"
    ok "Usuário de sistema $FARO_USER criado (sem login)"
}

baixar_codigo() {
    if [[ -d "$FARO_DIR/.git" ]]; then
        info "Atualizando código em $FARO_DIR"
        git -C "$FARO_DIR" fetch -q origin "$FARO_BRANCH"
        git -C "$FARO_DIR" checkout -q "$FARO_BRANCH"
        git -C "$FARO_DIR" merge -q --ff-only "origin/$FARO_BRANCH"
    else
        info "Clonando $FARO_REPO em $FARO_DIR"
        git clone -q --branch "$FARO_BRANCH" "$FARO_REPO" "$FARO_DIR"
    fi
    ok "Código na versão $(git -C "$FARO_DIR" log -1 --format='%h (%cd)' --date=short)"
}

preparar_venv() {
    [[ -x "$FARO_DIR/.venv/bin/python" ]] || python3 -m venv "$FARO_DIR/.venv"
    "$FARO_DIR/.venv/bin/pip" install -q --upgrade pip >/dev/null
    "$FARO_DIR/.venv/bin/pip" install -q -r "$FARO_DIR/requirements.txt"
    ok "Ambiente Python pronto ($FARO_DIR/.venv)"
}

preparar_pastas() {
    install -d -o "$FARO_USER" -g "$FARO_USER" -m 0755 "$FARO_WWW"
    ok "Página será gerada em $FARO_WWW/index.html"
}

# ---------------------------------------------------------------------------
# systemd: serviço oneshot + timer
# ---------------------------------------------------------------------------

escrever_units() {
    cat > "$UNIT_SERVICE" <<EOF
# Gerado por deploy/deploy.sh do Faro — não edite à mão; rode "deploy.sh update".
[Unit]
Description=Faro — gera a página do radar tech do time
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=${FARO_USER}
Group=${FARO_USER}
Environment=FARO_CACHE_DIR=${CACHE_DIR}
CacheDirectory=faro
ExecStart=${FARO_DIR}/.venv/bin/python ${FARO_DIR}/faro.py --no-open --out ${FARO_WWW}/index.html ${FARO_ARGS}
TimeoutStartSec=10min
Nice=10
# Isolamento: só escreve na pasta da página e no próprio cache.
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=${FARO_WWW}
EOF

    cat > "$UNIT_TIMER" <<EOF
# Gerado por deploy/deploy.sh do Faro — não edite à mão; rode "deploy.sh update".
[Unit]
Description=Faro — atualização periódica da página

[Timer]
OnCalendar=${FARO_AGENDA}
Persistent=true
RandomizedDelaySec=3min
Unit=${SERVICO}.service

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable -q --now "${SERVICO}.timer"
    ok "Timer do systemd ativo (OnCalendar=${FARO_AGENDA})"
}

gerar_agora() {
    info "Gerando a página (baixa feeds, imagens e traduções; pode levar ~1 min na 1ª vez)…"
    if systemctl start "${SERVICO}.service"; then
        ok "Página gerada: $(journalctl -u "${SERVICO}.service" -n 50 --no-pager -o cat | grep -E 'itens .* em ' | tail -1)"
    else
        err "A geração falhou. Veja: journalctl -u ${SERVICO}.service -n 50"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# nginx: snippet próprio + uma linha de include em cada bloco server
# ---------------------------------------------------------------------------

site_nginx() {
    # Arquivo do site que recebe o include. Segue symlink (sed -i num link o trocaria por arquivo).
    local site="$FARO_NGINX_SITE"
    if [[ -z "$site" ]]; then
        site="$(grep -lsE 'listen[^;]*default_server' /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf 2>/dev/null | head -1 || true)"
    fi
    [[ -n "$site" && "$site" != "nenhum" ]] && readlink -f "$site" || true
}

configurar_nginx() {
    if ! command -v nginx >/dev/null; then
        warn "nginx não encontrado: a página fica em $FARO_WWW/index.html (sirva como preferir)"
        return
    fi
    local site
    site="$(site_nginx)"
    if [[ -z "$site" ]]; then
        warn "Nenhum site nginx escolhido. Para publicar, inclua dentro do bloco server do seu site:"
        warn "    $LINHA_INCLUDE"
        escrever_snippet
        return
    fi

    escrever_snippet
    if grep -qF "snippets/faro.conf" "$site"; then
        ok "nginx: $site já inclui o Faro"
    else
        local backup="/var/backups/faro-nginx-$(basename "$site").$(date +%Y%m%d-%H%M%S)"
        cp -p "$site" "$backup"
        # Uma linha logo após cada server_name: entra em todos os blocos server (http e https).
        sed -i "/^[[:space:]]*server_name[[:space:]]/a\\    ${LINHA_INCLUDE}" "$site"
        if ! grep -qF "snippets/faro.conf" "$site"; then
            cp -p "$backup" "$site"
            warn "Não achei 'server_name' em $site; inclua à mão dentro do bloco server: $LINHA_INCLUDE"
            return
        fi
        if ! nginx -t -q 2>/dev/null; then
            cp -p "$backup" "$site"
            err "nginx -t falhou com o include; restaurei $site. Detalhes:"
            nginx -t || true
            return 1
        fi
        ok "nginx: include adicionado em $site (backup em $backup)"
    fi
    nginx -t -q && systemctl reload nginx
    ok "nginx recarregado"
}

escrever_snippet() {
    install -d /etc/nginx/snippets
    cat > "$SNIPPET" <<EOF
# Faro — gerado por deploy/deploy.sh; incluído nos blocos server do site.
location = ${FARO_URL_PATH} {
    absolute_redirect off;
    return 301 ${FARO_URL_PATH}/;
}
location ${FARO_URL_PATH}/ {
    alias ${FARO_WWW}/;
    index index.html;
    add_header Cache-Control "no-cache";
}
EOF
}

remover_nginx() {
    command -v nginx >/dev/null || return 0
    local arquivos
    arquivos="$(grep -lsF "snippets/faro.conf;  ${MARCA}" /etc/nginx/sites-enabled/* /etc/nginx/sites-available/* /etc/nginx/conf.d/*.conf 2>/dev/null || true)"
    for f in $arquivos; do
        f="$(readlink -f "$f")"
        sed -i "\\|snippets/faro.conf;  ${MARCA}|d" "$f"
        ok "nginx: include removido de $f"
    done
    rm -f "$SNIPPET"
    nginx -t -q && systemctl reload nginx && ok "nginx recarregado"
}

# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

endereco() {
    local host
    host="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "http://${host:-<servidor>}${FARO_URL_PATH}/"
}

cmd_install() {
    preflight
    instalar_dependencias
    criar_usuario
    baixar_codigo
    preparar_venv
    preparar_pastas
    escrever_units
    configurar_nginx
    gerar_agora
    echo
    ok "Faro instalado. Acesse: $(endereco)"
}

cmd_update() {
    preflight
    baixar_codigo
    preparar_venv
    preparar_pastas
    escrever_units
    configurar_nginx   # recoloca o include se outro deploy reescreveu o site
    gerar_agora
}

cmd_run() {
    preflight
    gerar_agora
}

cmd_status() {
    echo "== Timer";   systemctl list-timers "${SERVICO}.timer" --no-pager | head -3
    echo "== Última execução"
    journalctl -u "${SERVICO}.service" -n 200 --no-pager -o short-iso | grep -E 'itens .* em |ERRO|falh' | tail -3 || true
    echo "== Página"
    if [[ -f "$FARO_WWW/index.html" ]]; then
        echo "$FARO_WWW/index.html — gerada há $(( ($(date +%s) - $(stat -c %Y "$FARO_WWW/index.html")) / 60 )) min"
    else
        echo "ainda não gerada"
    fi
    echo "== nginx"
    local site
    site="$(site_nginx)"
    if [[ -n "$site" ]] && grep -qF "snippets/faro.conf" "$site"; then
        echo "include presente em $site"
        curl -s -o /dev/null -w "GET http://127.0.0.1${FARO_URL_PATH}/ → HTTP %{http_code}\n" "http://127.0.0.1${FARO_URL_PATH}/" || true
    else
        warn "include do Faro ausente no nginx (outro deploy reescreveu o site?). Rode: deploy.sh update"
    fi
}

cmd_uninstall() {
    preflight
    systemctl disable -q --now "${SERVICO}.timer" 2>/dev/null || true
    rm -f "$UNIT_SERVICE" "$UNIT_TIMER"
    systemctl daemon-reload
    ok "Timer e serviço removidos"
    remover_nginx
    rm -rf "$FARO_WWW" "$CACHE_DIR"
    rmdir --ignore-fail-on-non-empty /var/lib/faro 2>/dev/null || true
    if id "$FARO_USER" &>/dev/null; then
        userdel "$FARO_USER"
        ok "Usuário $FARO_USER removido"
    fi
    ok "Página e cache removidos. O código continua em $FARO_DIR (apague com: rm -rf $FARO_DIR)"
}

case "${1:-}" in
    install)   cmd_install ;;
    update)    cmd_update ;;
    run)       cmd_run ;;
    status)    cmd_status ;;
    uninstall) cmd_uninstall ;;
    *)
        echo "Uso: $0 {install|update|run|status|uninstall}"
        exit 1
        ;;
esac
