# 📡 Faro

**Radar de tecnologia para o time de desenvolvimento, em português.** Roda localmente, é gratuito e não usa chave de API.

Junta feeds RSS de fontes para desenvolvedores (projetos em alta no GitHub, Show HN, IA aplicada a código, Node/React, DevOps, arquitetura), pontua cada item pela relevância para a stack do time, descarta o ruído (promoção, celular, games, fofoca), traduz para pt-BR o que está em outro idioma e gera **uma página HTML estática** em tema escuro, que abre direto no navegador.

## O que você vê

- **Lista em linhas**, ordenada por relevância e dividida em três faixas: *Destaques para o time*, *Vale olhar* e *Outros*. Também dá para ver por data, agrupada por dia.
- **Por que é relevante:** cada item mostra os termos da stack que ele cita (ex.: `IA p/ código · Node.js · MCP`).
- **Filtros:** categoria (IA, GitHub, Ferramentas, JS/TS, DevOps, Arquitetura, Banco de dados, Segurança, Linux…), fonte e busca por palavra-chave, que ignora acentos.
- **Resumo sob demanda:** clicar na linha abre o resumo, com os botões *Ler matéria completa* / *Abrir no GitHub* e **Copiar para o time**, que copia título, termos, resumo e link prontos para colar no chat.
- Itens já lidos ficam esmaecidos.
- **Teclado:** `J`/`K` navegam, `Enter` abre e fecha, `O` abre o link, `C` copia, `/` busca.

## Instalação (Linux)

```bash
git clone git@github.com:brunomrtns/faro.git ~/faro
cd ~/faro
python3 -m venv .venv            # se faltar: sudo apt install python3-venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python faro.py         # baixa, gera e abre no navegador
```

A página é gerada em `~/.cache/tech-news/index.html`.

### Comando `faro` no terminal

```bash
echo "alias faro='~/faro/.venv/bin/python ~/faro/faro.py'" >> ~/.bashrc
source ~/.bashrc
faro
```

### Atalho na área de trabalho e no menu (GNOME)

```bash
cat > ~/.local/share/applications/faro.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Faro
Comment=Radar tech do time: inovações, ferramentas e projetos do GitHub
Exec=$HOME/faro/.venv/bin/python $HOME/faro/faro.py
Icon=applications-internet
Terminal=false
Categories=Network;News;
EOF
cp ~/.local/share/applications/faro.desktop "$(xdg-user-dir DESKTOP)/"
chmod +x "$(xdg-user-dir DESKTOP)/faro.desktop"
gio set "$(xdg-user-dir DESKTOP)/faro.desktop" metadata::trusted true
```

### Atualizar sozinho de hora em hora (opcional)

Com `crontab -e`:

```
0 * * * * $HOME/faro/.venv/bin/python $HOME/faro/faro.py --no-open
```

## Instalação em servidor (nginx + systemd)

Para deixar o Faro publicado para o time inteiro, numa máquina Linux com systemd. O nginx é opcional.

```bash
git clone https://github.com/brunomrtns/faro.git /opt/faro
sudo /opt/faro/deploy/deploy.sh install
```

Ou, sem clonar antes:

```bash
curl -fsSL https://raw.githubusercontent.com/brunomrtns/faro/main/deploy/deploy.sh | sudo bash -s install
```

O `install`:

- instala `git`, `python3` e `python3-venv` se faltarem, e cria o `.venv` em `/opt/faro`;
- cria o usuário de sistema `faro` (sem login). A geração roda com ele, isolada pelo systemd: só escreve na pasta da página e no cache (`/var/cache/faro`);
- cria `faro.service` e `faro.timer`, que geram `/var/lib/faro/www/index.html` de hora em hora;
- publica em **`/faro/`** no nginx. Ele escreve `snippets/faro.conf` e acrescenta **uma linha** `include snippets/faro.conf;  # faro` em cada bloco `server` do site que é `default_server`, sem mexer no resto. Antes de recarregar, faz backup em `/var/backups/` e roda `nginx -t`; se o teste falhar, restaura o arquivo;
- gera a primeira página na hora.

Outros comandos: `deploy.sh update` (versão nova do repositório + reaplica tudo), `run` (gera agora), `status` e `uninstall`.

> Se outro deploy reescrever o arquivo do site no nginx, o `include` some. O `deploy.sh status` avisa e o `deploy.sh update` coloca de volta.

O script não guarda nenhum IP, senha ou nome de máquina. Tudo tem padrão e pode ser trocado por variável de ambiente:

| Variável | Padrão |
|---|---|
| `FARO_URL_PATH` | `/faro` |
| `FARO_AGENDA` | `hourly` (qualquer `OnCalendar` do systemd, ex.: `*:0/30`) |
| `FARO_ARGS` | vazio (ex.: `"--max 30 --dias 14"`) |
| `FARO_NGINX_SITE` | site com `default_server` (`nenhum` = não mexe no nginx) |
| `FARO_DIR` / `FARO_WWW` / `FARO_USER` | `/opt/faro` / `/var/lib/faro/www` / `faro` |
| `FARO_REPO` / `FARO_BRANCH` | este repositório / `main` |

Exemplo: `sudo FARO_URL_PATH=/radar FARO_AGENDA='*:0/30' /opt/faro/deploy/deploy.sh install`

## Opções

| Opção | O que faz |
|---|---|
| `--no-open` | só gera o arquivo, sem abrir o navegador |
| `--max N` | máximo de itens por fonte (padrão 20) |
| `--dias N` | ignora itens mais velhos que N dias (padrão 21) |
| `--sem-traducao` | mantém as fontes estrangeiras no idioma original |
| `--sem-capa` | não busca a imagem de capa nas páginas (mais rápido) |
| `--out arquivo.html` | grava em outro lugar |

## Personalizar

Tudo fica no topo do `faro.py`:

- **`FEEDS`**: fontes (nome, URL, categoria padrão, peso da fonte, se é em português, se é feed do GitHub).
- **`PERFIL_TIME`**: termos da stack do time e quanto cada um vale. É o que define os destaques.
- **`RUIDO`**: termos que derrubam a nota; item com nota negativa é descartado.
- **`CATEGORIAS`**: regras dos filtros de assunto.
- **`NOTA_DESTAQUE` / `NOTA_VALE_OLHAR`**: notas de corte das faixas.

## Como funciona

- **Uma dependência:** [`feedparser`](https://github.com/kurtmckee/feedparser). O resto é biblioteca padrão do Python. Os feeds são baixados em paralelo, e um feed fora do ar não derruba os outros.
- **Projetos em alta no GitHub:** vêm do espelho em RSS [GitHubTrendingRSS](https://github.com/mshibanami/GitHubTrendingRSS). A imagem é o cartão de prévia do próprio GitHub.
- **Imagens:** quando o feed não traz imagem, o Faro lê o começo da página e pega a `og:image`.
- **Tradução:** usa a API pública e gratuita [translate-api-google-node-vercel](https://github.com/DIEGOHORVATTI/translate-api-google-node-vercel) (`translate-google-api-v1.vercel.app`), em lotes. Não é uma API oficial: se ela falhar, o item aparece no original e é traduzido numa próxima execução.
- **Cache:** traduções e imagens ficam em `~/.cache/tech-news/` (ou em `FARO_CACHE_DIR`), então cada texto e cada página só são consultados uma vez.
- **Página:** um arquivo só, com HTML, CSS e JS embutidos e sem servidor. Os horários relativos ("há 2 h", "Hoje") são calculados ao abrir, então continuam certos mesmo horas depois. Todo texto dos feeds entra como texto, nunca como HTML.
