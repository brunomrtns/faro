#!/usr/bin/env python3
"""
Faro — radar local de tecnologia para o time de desenvolvimento, em português.

Junta feeds RSS/Atom gratuitos (sem chave de API) de fontes para desenvolvedores:
projetos em alta no GitHub, Show HN, IA aplicada a código, Node/React, DevOps,
arquitetura. Cada item ganha uma pontuação de relevância para a stack do time
(PERFIL_TIME, logo abaixo), o ruído (promoção, celular, games, fofoca) é descartado,
o que está em inglês é traduzido para pt-BR e tudo vira UMA página HTML estática,
em tema escuro, que abre direto no navegador.

Uso:
    python3 faro.py                  # baixa, gera e abre no navegador
    python3 faro.py --no-open        # só gera o arquivo
    python3 faro.py --max 20         # máximo de itens por fonte (padrão 20)
    python3 faro.py --dias 21        # ignora itens mais velhos que N dias (padrão 21)
    python3 faro.py --sem-traducao   # mantém as fontes estrangeiras no original
    python3 faro.py --sem-capa       # não busca imagem de capa nas páginas
    python3 faro.py --out arq.html

Dependência única: feedparser (pip install feedparser).

Tradução: usa a API pública e gratuita translate-google-api-v1 (Google Tradutor
servido pela Vercel, sem chave): github.com/DIEGOHORVATTI/translate-api-google-node-vercel.
Não é uma API oficial; se falhar ou limitar, o item aparece no idioma original e é
traduzido numa próxima execução.
Tudo o que já foi traduzido fica em cache local.

Para ajustar ao seu gosto, edite FEEDS, PERFIL_TIME, RUIDO e CATEGORIAS.
"""

import argparse
import calendar
import html
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import feedparser
except ImportError:
    sys.exit("Falta a biblioteca feedparser. Instale com: pip install feedparser")

# ---------------------------------------------------------------------------
# Fontes
# ---------------------------------------------------------------------------
# nome:   como aparece na página
# url:    endereço do feed
# cat:    categoria padrão (usada quando as palavras-chave não indicam outra)
# pt:     True se o feed já é em português (não traduz)
# peso:   bônus de relevância da fonte (fontes muito curadas ganham mais)
# github: True para os feeds de repositórios em alta (título = dono/repo, não traduz)
# selo:   texto mostrado no lugar do horário (feeds sem data, como o GitHub em alta)

GT = "https://mshibanami.github.io/GitHubTrendingRSS"  # espelho em RSS do github.com/trending
FEEDS = [
    dict(nome="GitHub em alta",      url=f"{GT}/daily/all.xml",          cat="GitHub", peso=3, github=True, selo="em alta hoje"),
    dict(nome="GitHub TypeScript",   url=f"{GT}/weekly/typescript.xml",  cat="GitHub", peso=4, github=True, selo="em alta na semana"),
    dict(nome="GitHub JavaScript",   url=f"{GT}/weekly/javascript.xml",  cat="GitHub", peso=4, github=True, selo="em alta na semana"),
    dict(nome="GitHub Python",       url=f"{GT}/weekly/python.xml",      cat="GitHub", peso=2, github=True, selo="em alta na semana"),
    dict(nome="Show HN",             url="https://hnrss.org/show?points=60",              cat="Ferramentas", peso=2),
    dict(nome="Hacker News",         url="https://hnrss.org/frontpage?points=250",        cat="Engenharia",  peso=0),
    dict(nome="Lobsters",            url="https://lobste.rs/rss",                         cat="Engenharia",  peso=1),
    dict(nome="Simon Willison",      url="https://simonwillison.net/atom/everything/",    cat="IA",          peso=3),
    dict(nome="TLDR AI",             url="https://tldr.tech/api/rss/ai",                  cat="IA",          peso=1),
    dict(nome="Ollama",              url="https://ollama.com/blog/rss.xml",               cat="IA",          peso=2),
    dict(nome="Hugging Face",        url="https://huggingface.co/blog/feed.xml",          cat="IA",          peso=1),
    dict(nome="GitHub Changelog",    url="https://github.blog/changelog/feed/",           cat="Ferramentas", peso=2),
    dict(nome="GitHub Blog",         url="https://github.blog/feed/",                     cat="Ferramentas", peso=1),
    dict(nome="Node.js",             url="https://nodejs.org/en/feed/blog.xml",           cat="JS/TS",       peso=3),
    dict(nome="React",               url="https://react.dev/rss.xml",                     cat="JS/TS",       peso=3),
    dict(nome="JavaScript Weekly",   url="https://cprss.s3.amazonaws.com/javascriptweekly.com.xml", cat="JS/TS", peso=3),
    dict(nome="Node Weekly",         url="https://cprss.s3.amazonaws.com/nodeweekly.com.xml",       cat="JS/TS", peso=3),
    dict(nome="Changelog News",      url="https://changelog.com/news/feed",               cat="Ferramentas", peso=1),
    dict(nome="InfoQ",               url="https://feed.infoq.com/",                       cat="Arquitetura", peso=1),
    dict(nome="Martin Fowler",       url="https://martinfowler.com/feed.atom",            cat="Arquitetura", peso=2),
    dict(nome="Pragmatic Engineer",  url="https://newsletter.pragmaticengineer.com/feed", cat="Engenharia",  peso=1),
    dict(nome="The New Stack",       url="https://thenewstack.io/feed/",                  cat="DevOps",      peso=0),
    dict(nome="Akita",               url="https://akitaonrails.com/index.xml",            cat="Engenharia",  peso=1, pt=True),
    dict(nome="Diolinux",            url="https://diolinux.com.br/feed",                  cat="Linux",       peso=0, pt=True),
]

# ---------------------------------------------------------------------------
# Relevância para o time
# ---------------------------------------------------------------------------
# (rótulo exibido, peso, regex). Cada rótulo conta uma vez por item.
# Testado no texto ORIGINAL (antes da tradução), em título + resumo.
PERFIL_TIME = [
    ("IA p/ código",     4, r"coding agents?|ai[- ]coding|ai[- ]assisted|code generation|code review|claude code|codex|copilot|cursor|aider|cline|windsurf|vibe coding"),
    ("Claude",           3, r"claude|anthropic"),
    ("MCP",              4, r"\bmcp\b|model context protocol"),
    ("Agentes de IA",    3, r"ai agents?|agentic|agentes? de ia|multi-agent|subagents?"),
    ("LLM",              2, r"\bllms?\b|large language models?|\brag\b|embeddings?|fine-?tun\w*|ollama|vllm|llama\.cpp|local models?|prompt\w*"),
    ("Node.js",          4, r"node\.?js|\bnpm\b|\bpnpm\b|\byarn\b|\bbun\b|\bdeno\b|express\.?js"),
    ("TypeScript",       3, r"typescript"),
    ("React",            3, r"\breact\b|\bvite\b|vitest|redux|zustand|\bmui\b|material[- ]ui"),
    ("MongoDB",          3, r"mongo(db|ose)?"),
    ("Redis",            3, r"\bredis\b|valkey|pub/?sub"),
    ("PostgreSQL",       3, r"postgres(ql)?"),
    ("Tempo real",       3, r"socket\.io|websockets?|webrtc|server-sent events"),
    ("Voz/telefonia",    4, r"\bsip\b|voip|asterisk|kamailio|freeswitch|speech[- ]to[- ]text|text[- ]to[- ]speech|\btts\b|whisper|transcri(ption|be|ção|ções)|contact cent(er|re)|call cent(er|re)"),
    ("Mensageria",       3, r"whatsapp|telegram|chatbots?|omnichannel"),
    ("Testes",           2, r"\bjest\b|playwright|\be2e\b|end-to-end|unit tests?|test automation|testing"),
    ("Docker",           2, r"docker|podman|containers?"),
    ("CI/CD",            3, r"gitlab|ci/cd|github actions|semantic-release|continuous (integration|delivery)"),
    ("Observabilidade",  2, r"observability|opentelemetry|elasticsearch|kibana|grafana|prometheus|tracing"),
    ("Arquitetura",      2, r"microservices?|microsservi\w+|event[- ]driven|software architecture|arquitetura|monorepo|domain[- ]driven"),
    ("API",              2, r"openapi|swagger|rest api|graphql|\bgrpc\b"),
    ("Linux",            2, r"\blinux\b|rocky linux|\brhel\b|\brpm\b|systemd|nginx"),
    ("Segurança",        2, r"cve-\d+|vulnerabilit\w+|supply[- ]chain|security|seguran[cç]a"),
    ("Produtividade",    2, r"developer (productivity|experience)|refactor\w*|code quality|technical debt|d[ií]vida t[eé]cnica"),
    ("Open source",      1, r"open[- ]source|c[oó]digo aberto|self-hosted|\bcli\b|devtools?|developer tools?"),
]

# Ruído: cada termo encontrado tira pontos (até -8). Item com nota negativa é descartado.
RUIDO_PESO = -4
RUIDO = (r"deals?|discount|\d+% off|black (friday|november)|promo[cç][aã]o|desconto|cupom|on sale|prime day|"
         r"iphone|galaxy [sz]\d*|pixel \d|smartphones?|celular|video ?games?|gaming|xbox|playstation|nintendo|gta|"
         r"movies?|filmes?|netflix|disney|celebrit\w+|elon musk|trump|congress|lawsuit|stocks?|earnings|\bipo\b|"
         r"layoffs?|crypto\w*|bitcoin|tesla|cybertruck|electric vehicles?|power bank|headphones|earbuds|"
         r"smartwatch|scandal|esc[aâ]ndalo")

NOTA_DESTAQUE = 7    # a partir desta nota o item vai para "Destaques para o time"
NOTA_VALE_OLHAR = 3  # entre esta e a de destaque: "Vale olhar"

# Categorias de assunto (chips no topo). Ordem importa: a primeira que casar vence.
CATEGORIAS = [
    ("Segurança",      r"cve-\d+|vulnerabilit\w+|exploit|ransomware|malware|supply[- ]chain attack|backdoor|zero[- ]day"),
    ("IA",             r"\bai\b|\bia\b|\bllms?\b|claude|anthropic|openai|gpt[-\s]?\d*|gemini|copilot|agents?|agentic|machine learning|ollama|hugging ?face|\bmcp\b|\brag\b|embeddings?|inference|deepseek|qwen|mistral|llama"),
    ("JS/TS",          r"javascript|typescript|node\.?js|\bnpm\b|\breact\b|\bvite\b|\bbun\b|\bdeno\b|next\.?js|svelte|\bvue\b"),
    ("Banco de dados", r"postgres(ql)?|mongo(db)?|redis|valkey|sqlite|mysql|database|banco de dados|\bsql\b|clickhouse|duckdb"),
    ("DevOps",         r"docker|kubernetes|\bk8s\b|ci/cd|gitlab|github actions|terraform|ansible|observability|opentelemetry|grafana|prometheus|nginx|deploy\w*"),
    ("Arquitetura",    r"architecture|arquitetura|microservices?|event[- ]driven|distributed systems?|design patterns?|domain[- ]driven"),
    ("Linux",          r"\blinux\b|ubuntu|debian|fedora|rocky|kernel|systemd|wayland|flatpak|distro"),
    ("Ferramentas",    r"\bcli\b|terminal|editor|vs ?code|neovim|devtools?|developer tools?|\bgit\b|open[- ]source"),
]

# ---------------------------------------------------------------------------
# Parâmetros técnicos
# ---------------------------------------------------------------------------
TIMEOUT_S = 15          # timeout de cada download de feed
MAX_RESUMO = 600        # caracteres máximos do resumo exibido
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) faro/2.0 (+https://github.com/brunomrtns/faro)"

DIR_CACHE = Path.home() / ".cache" / "tech-news"
SAIDA_PADRAO = DIR_CACHE / "index.html"
CACHE_OG = DIR_CACHE / "og-cache.json"          # imagens de capa já procuradas, por link
TIMEOUT_OG_S = 6
BYTES_OG = 96_000       # as meta tags ficam no <head>: basta ler o começo da página
CACHE_TRADUCAO = DIR_CACHE / "traducoes.json"   # traduções já feitas, por texto original
# POST {"text", "from", "to"} -> string JSON com a tradução (preserva as quebras de linha).
URL_TRADUTOR = "https://translate-google-api-v1.vercel.app/translate"
TIMEOUT_TRADUCAO_S = 20
TAMANHO_LOTE = 3500     # caracteres por pedido de tradução

# Compila as regex uma vez só.
_PERFIL_RE = [(rot, peso, re.compile(r"(?<![\w-])(" + rx + r")(?![\w-])", re.I)) for rot, peso, rx in PERFIL_TIME]
_RUIDO_RE = re.compile(r"(?<![\w-])(" + RUIDO + r")(?![\w-])", re.I)
_CAT_RE = [(nome, re.compile(r"(?<![\w-])(" + rx + r")(?![\w-])", re.I)) for nome, rx in CATEGORIAS]
_IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
_OG_RE = [re.compile(p, re.I) for p in (
    r"<meta[^>]+(?:property|name)=[\"'](?:og:image|twitter:image)[\"'][^>]+content=[\"']([^\"']+)",
    r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+(?:property|name)=[\"'](?:og:image|twitter:image)[\"']",
)]

# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------


def ler_cache(arquivo: Path) -> dict:
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gravar_cache(arquivo: Path, dados: dict) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def limpar_html(texto: str, limite: int = MAX_RESUMO) -> str:
    """Remove tags e entidades HTML, colapsa espaços e corta no tamanho máximo."""
    texto = re.sub(r"<(script|style|pre|code)[^>]*>.*?</\1>", " ", texto or "", flags=re.S | re.I)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html.unescape(texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) > limite:
        texto = texto[:limite].rsplit(" ", 1)[0] + "…"
    return texto

# ---------------------------------------------------------------------------
# Classificação e relevância
# ---------------------------------------------------------------------------


def classificar(titulo: str, resumo: str, padrao: str) -> str:
    """Categoria de assunto: pelo título primeiro (mais confiável), depois pelo resumo."""
    for texto in (titulo, resumo):
        for nome, regex in _CAT_RE:
            if regex.search(texto):
                return nome
    return padrao


def pontuar(titulo: str, resumo: str, peso_fonte: int) -> tuple:
    """Nota de relevância para o time e os rótulos que a justificam.
    Termo no título vale o peso cheio; só no resumo vale metade (arredondado para cima)."""
    nota, rotulos = peso_fonte, []
    for rotulo, peso, regex in _PERFIL_RE:
        if regex.search(titulo):
            nota += peso
            rotulos.append(rotulo)
        elif regex.search(resumo):
            nota += (peso + 1) // 2
            rotulos.append(rotulo)
    ruido = len({m.group(0).lower() for m in _RUIDO_RE.finditer(f"{titulo} {resumo[:300]}")})
    nota += max(RUIDO_PESO * ruido, 2 * RUIDO_PESO)
    return nota, rotulos

# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------


def data_da_entrada(entrada) -> float:
    """Timestamp (epoch, UTC) da publicação; 0 se o feed não informar."""
    for campo in ("published_parsed", "updated_parsed", "created_parsed"):
        valor = entrada.get(campo)
        if valor:
            return float(calendar.timegm(valor))  # struct_time do feedparser já é UTC
    return 0.0


def extrair_imagem(entrada) -> str:
    """Thumbnail da notícia: media:thumbnail, media:content, enclosure ou 1º <img> do HTML."""
    for campo in ("media_thumbnail", "media_content"):
        for midia in entrada.get(campo) or []:
            url = midia.get("url", "")
            if url and midia.get("medium", "image") == "image" and "video" not in midia.get("type", ""):
                return url
    for link in entrada.get("links") or []:
        if link.get("rel") == "enclosure" and link.get("type", "").startswith("image") and link.get("href"):
            return link["href"]
    textos = [entrada.get("summary", "")] + [c.get("value", "") for c in entrada.get("content") or []]
    for texto in textos:
        achou = _IMG_RE.search(texto or "")
        if achou and not achou.group(1).startswith("data:"):
            return html.unescape(achou.group(1))
    return ""


def item_github(e) -> dict:
    """Repositório em alta: descrição do projeto + começo do README; imagem = cartão do GitHub."""
    bruto = e.get("summary", "")
    descricao = limpar_html(re.split(r"</p>", bruto, maxsplit=1, flags=re.I)[0], 300)
    readme = bruto.split("<hr", 1)[1] if "<hr" in bruto else ""
    readme = re.sub(r"^[^>]*>", "", readme)  # resto da tag <hr ...>
    resumo = limpar_html(f"{descricao}. {limpar_html(readme, 2000)}" if descricao else readme)
    caminho = urllib.parse.urlparse(e.get("link", "")).path.strip("/")
    return {
        "titulo": e.get("title", "").strip() or caminho,
        "resumo": resumo,
        "imagem": f"https://opengraph.githubassets.com/1/{caminho}" if caminho.count("/") == 1 else "",
    }


def baixar_feed(feed_cfg: dict, maximo: int, limite_ts: float) -> list:
    """Baixa e converte um feed numa lista de dicionários de notícia."""
    for _ in range(2):  # alguns servidores (ex.: hnrss) às vezes travam no 1º handshake
        feed = feedparser.parse(feed_cfg["url"], agent=USER_AGENT)
        if feed.entries or not feed.bozo:
            break
    if feed.bozo and not feed.entries:
        raise RuntimeError(str(feed.get("bozo_exception", "feed inválido")))

    agora = time.time()
    noticias = []
    for e in feed.entries[:maximo]:
        if feed_cfg.get("github"):
            base = item_github(e)
            ts = agora  # lista de "em alta" não tem data: vale o momento da coleta
        else:
            # Prefere o conteúdo completo quando o resumo vem vazio ou curtíssimo.
            bruto = e.get("summary", "")
            if len(bruto) < 80 and e.get("content"):
                bruto = e["content"][0].get("value", bruto)
            base = {"titulo": limpar_html(e.get("title", ""), 300), "resumo": limpar_html(bruto),
                    "imagem": extrair_imagem(e)}
            ts = data_da_entrada(e)
            if ts and ts < limite_ts:
                continue  # velho demais
        if not base["titulo"]:
            continue
        if base["resumo"] == base["titulo"]:
            base["resumo"] = ""

        nota, rotulos = pontuar(base["titulo"], base["resumo"], feed_cfg.get("peso", 0))
        if nota < 0:
            continue  # ruído: promoção, celular, games, fofoca…
        noticias.append({
            **base,
            "titulo_original": "",          # preenchido quando o título é traduzido
            "link": e.get("link", ""),
            "fonte": feed_cfg["nome"],
            "pt": feed_cfg.get("pt", False),
            "github": feed_cfg.get("github", False),
            "selo": feed_cfg.get("selo", ""),
            "categoria": feed_cfg["cat"] if feed_cfg.get("github")
                         else classificar(base["titulo"], base["resumo"], feed_cfg["cat"]),
            "nota": nota,
            "rotulos": rotulos,
            "ts": ts,
        })
    return noticias


def coletar(maximo: int, dias: int) -> tuple:
    """Baixa todos os feeds em paralelo. Retorna (notícias, lista de fontes com erro)."""
    socket.setdefaulttimeout(TIMEOUT_S)  # feedparser usa urllib, que respeita isto
    limite_ts = time.time() - dias * 86400
    noticias, erros = [], []
    with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
        tarefas = {pool.submit(baixar_feed, f, maximo, limite_ts): f["nome"] for f in FEEDS}
        for tarefa in as_completed(tarefas):
            nome = tarefas[tarefa]
            try:
                itens = tarefa.result()
                noticias.extend(itens)
                print(f"  ok   {nome:<19} {len(itens):>3} itens")
            except Exception as exc:  # um feed fora do ar não derruba os outros
                erros.append(nome)
                print(f"  ERRO {nome:<19} {exc}", file=sys.stderr)

    # Mesmo link em duas fontes (ex.: repo em alta no dia e na semana): fica o de maior nota.
    melhores = {}
    for n in noticias:
        chave = n["link"] or n["titulo"]
        if chave not in melhores or n["nota"] > melhores[chave]["nota"]:
            melhores[chave] = n
    unicas = sorted(melhores.values(), key=lambda n: n["ts"], reverse=True)
    return unicas, erros

# ---------------------------------------------------------------------------
# Imagem de capa (og:image) para itens sem imagem no feed
# ---------------------------------------------------------------------------


def buscar_og_image(link: str) -> str:
    """Lê o começo da página e devolve a imagem de capa (og:image); '' se não achar."""
    try:
        req = urllib.request.Request(link, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_OG_S) as resp:
            if "html" not in resp.headers.get("Content-Type", ""):
                return ""
            cabeca = resp.read(BYTES_OG).decode("utf-8", "ignore")
    except Exception:
        return ""
    for regex in _OG_RE:
        achou = regex.search(cabeca)
        if achou and achou.group(1).startswith("http"):
            return html.unescape(achou.group(1))
    return ""


def completar_imagens(noticias: list) -> None:
    """Para itens sem imagem no feed, busca a og:image em paralelo, usando cache em disco."""
    cache = ler_cache(CACHE_OG)
    faltando = [n["link"] for n in noticias if not n["imagem"] and n["link"] and n["link"] not in cache]
    if faltando:
        print(f"Buscando imagem de capa de {len(faltando)} itens…")
        with ThreadPoolExecutor(max_workers=24) as pool:
            for link, img in zip(faltando, pool.map(buscar_og_image, faltando)):
                cache[link] = img

    for n in noticias:
        if not n["imagem"]:
            n["imagem"] = cache.get(n["link"], "")

    # Imagem repetida em 3+ itens é a genérica do site (ex.: logo da newsletter): descarta.
    contagem = Counter(n["imagem"] for n in noticias if n["imagem"])
    for n in noticias:
        if contagem.get(n["imagem"], 0) >= 3:
            n["imagem"] = ""

    atuais = {n["link"] for n in noticias}  # cache só com links ainda presentes nos feeds
    gravar_cache(CACHE_OG, {k: v for k, v in cache.items() if k in atuais})

# ---------------------------------------------------------------------------
# Tradução para pt-BR
# ---------------------------------------------------------------------------

_bloqueado = False  # vira True quando a API segue limitando/falhando mesmo após esperar


def traduzir(texto: str) -> str:
    """Traduz para pt-BR (idioma de origem detectado) pela API pública; '' se falhar.
    Em 429 ou erro 5xx (limite ou Google recusando a Vercel) espera e tenta mais uma vez;
    se persistir, desiste do resto nesta execução (o que faltou fica para a próxima)."""
    global _bloqueado
    dados = json.dumps({"text": texto, "from": "auto", "to": "pt"}).encode()
    for espera in (0, 4):
        if _bloqueado:
            return ""
        time.sleep(espera)
        try:
            req = urllib.request.Request(URL_TRADUTOR, data=dados, method="POST",
                                         headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_TRADUCAO_S) as resp:
                resposta = json.loads(resp.read().decode("utf-8"))
            return resposta if isinstance(resposta, str) else ""
        except urllib.error.HTTPError as erro:
            if erro.code != 429 and erro.code < 500:
                return ""
        except Exception:
            return ""
    _bloqueado = True
    return ""


def traduzir_lote(lote: list) -> list:
    """Traduz vários textos num pedido só, um por linha (os textos já não têm quebra de linha).
    Se o número de linhas voltar diferente, refaz um a um para não desalinhar."""
    traducao = traduzir("\n".join(lote))
    if not traducao:
        return [""] * len(lote)  # falhou o pedido inteiro: não adianta repetir texto a texto agora
    linhas = [l.strip() for l in traducao.split("\n")]
    if len(linhas) == len(lote) and all(linhas):
        return linhas
    return [traduzir(t).strip() for t in lote]


def traduzir_noticias(noticias: list) -> None:
    """Traduz título e resumo dos itens estrangeiros, usando cache em disco.
    Repositórios do GitHub mantêm o nome (dono/repo) e só traduzem a descrição."""
    cache = ler_cache(CACHE_TRADUCAO)
    estrangeiras = [n for n in noticias if not n["pt"]]
    campos = lambda n: ("resumo",) if n["github"] else ("titulo", "resumo")
    pendentes = sorted({n[c] for n in estrangeiras for c in campos(n) if n[c] and n[c] not in cache})

    if pendentes:
        print(f"Traduzindo {len(pendentes)} textos para pt-BR…")
        lotes, lote, tamanho = [], [], 0
        for texto in pendentes:
            if lote and tamanho + len(texto) > TAMANHO_LOTE:
                lotes.append(lote)
                lote, tamanho = [], 0
            lote.append(texto)
            tamanho += len(texto) + 1
        if lote:
            lotes.append(lote)
        with ThreadPoolExecutor(max_workers=3) as pool:
            for lote, traducoes in zip(lotes, pool.map(traduzir_lote, lotes)):
                for texto, traducao in zip(lote, traducoes):
                    if traducao:  # falha não entra no cache: tenta de novo na próxima execução
                        cache[texto] = traducao
        falhas = sum(1 for t in pendentes if t not in cache)
        if falhas:
            motivo = "a API de tradução limitou ou falhou; " if _bloqueado else ""
            print(f"  {falhas} textos ficaram no original ({motivo}tenta de novo na próxima execução)",
                  file=sys.stderr)

    usados = set()
    for n in estrangeiras:
        original = n["titulo"]
        for c in campos(n):
            if n[c] in cache:
                usados.add(n[c])
                n[c] = cache[n[c]]
        if n["titulo"] != original:
            n["titulo_original"] = original

    gravar_cache(CACHE_TRADUCAO, {k: v for k, v in cache.items() if k in usados})

# ---------------------------------------------------------------------------
# Página HTML
# ---------------------------------------------------------------------------

# Os dados entram como JSON em __DADOS__ e o JavaScript monta a lista. Renderizar no
# navegador permite que "há 2 h" e "Hoje/Ontem" fiquem certos mesmo quando você
# reabre o arquivo horas depois.
MODELO_HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Faro · radar tech do time</title>
<style>
  :root {
    --bg:#0d1014; --card:#151a21; --card2:#1b222b; --borda:#252d38; --txt:#e8edf2;
    --sub:#8c96a3; --destaque:#5aa7ff; --ouro:#f2c94c;
    --IA:#c79bff; --GitHub:#e6edf3; --Ferramentas:#5ee0c8; --JSTS:#f7df1e; --Bancodedados:#ff9f5a;
    --DevOps:#6cc4ff; --Arquitetura:#f28fad; --Linux:#6fdc8c; --Seguranca:#ff7a70; --Engenharia:#9fb3c8;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--txt);
         font:15px/1.45 system-ui,-apple-system,"Segoe UI",Ubuntu,sans-serif; }
  button, input, select { font:inherit; color:inherit; }

  /* ---------- Topo fixo ---------- */
  header { position:sticky; top:0; z-index:5; background:rgba(13,16,20,.94);
           backdrop-filter:blur(8px); border-bottom:1px solid var(--borda); }
  .barra { max-width:1100px; margin:0 auto; padding:12px 20px 10px; display:flex; gap:10px;
           flex-wrap:wrap; align-items:center; }
  h1 { font-size:18px; margin:0 14px 0 0; white-space:nowrap; }
  #busca { flex:1; min-width:200px; }
  input, select { background:var(--card); border:1px solid var(--borda); border-radius:8px; padding:8px 12px; }
  input:focus, select:focus { outline:2px solid var(--destaque); outline-offset:-1px; }
  .chips { max-width:1100px; margin:0 auto; padding:0 20px 12px; display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
  .chip { background:var(--card); color:var(--sub); border:1px solid var(--borda); border-radius:999px;
          padding:4px 12px; cursor:pointer; font-size:13px; display:flex; gap:6px; align-items:center; }
  .chip:hover { color:var(--txt); }
  .chip .bolinha { width:8px; height:8px; border-radius:50%; background:var(--cor, var(--sub)); }
  .chip .qtd { opacity:.7; font-variant-numeric:tabular-nums; }
  .chip.ativo { color:var(--txt); border-color:var(--cor, var(--destaque));
                background:color-mix(in srgb, var(--cor, var(--destaque)) 18%, var(--card)); }
  .status { margin-left:auto; color:var(--sub); font-size:12px; }
  .erro { color:#f0883e; }

  /* ---------- Lista em linhas ---------- */
  main { max-width:1100px; margin:0 auto; padding:4px 20px 60px; }
  .grupo { display:flex; align-items:baseline; gap:10px; margin:28px 0 10px; font-size:14px;
           text-transform:uppercase; letter-spacing:.06em; color:var(--sub); }
  .grupo b { color:var(--txt); }
  .grupo::after { content:""; flex:1; height:1px; background:var(--borda); }

  .item { background:var(--card); border:1px solid var(--borda); border-left:4px solid var(--cor);
          border-radius:10px; margin-bottom:12px; overflow:hidden; transition:background .12s, border-color .12s; }
  .item:hover, .item:focus-within { background:var(--card2); border-color:var(--cor); }
  .cabeca { display:flex; gap:18px; padding:14px; cursor:pointer; outline:none; }
  .capa { position:relative; flex:none; width:220px; aspect-ratio:16/9; border-radius:8px;
          background:var(--card2); overflow:hidden; }
  .capa img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; display:block; }
  .capa .sem { position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
               font-size:28px; font-weight:800; letter-spacing:2px; color:var(--cor);
               background:radial-gradient(circle at 30% 20%, color-mix(in srgb, var(--cor) 22%, transparent), transparent 70%); }
  .texto { flex:1; min-width:0; display:flex; flex-direction:column; gap:6px; }
  .meta { display:flex; gap:8px; align-items:center; flex-wrap:wrap; color:var(--sub); font-size:13px; }
  .meta .fonte { color:var(--txt); font-weight:600; opacity:.9; }
  .tag { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em;
         padding:2px 8px; border-radius:5px; color:#0d1014; background:var(--cor); }
  .estrela { color:var(--ouro); font-weight:700; font-size:12.5px; }
  .item h3 { margin:0; font-size:19px; line-height:1.3; font-weight:700; overflow-wrap:anywhere; }
  .previa { margin:0; color:#aeb8c4; font-size:14.5px; line-height:1.5;
            display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
  .rotulos { display:flex; gap:6px; flex-wrap:wrap; }
  .rotulos span { font-size:11.5px; color:#c9d3de; background:var(--card2); border:1px solid var(--borda);
                  border-radius:999px; padding:1px 9px; }
  .seta { flex:none; align-self:center; color:var(--sub); font-size:20px; transition:transform .15s; }
  .item.aberto .seta { transform:rotate(180deg); }
  .item.aberto .previa { display:none; }

  .detalhe { display:none; padding:0 18px 18px 252px; }
  .item.aberto .detalhe { display:block; }
  .detalhe .original { color:var(--sub); font-size:13px; font-style:italic; margin:0 0 8px; }
  .detalhe .resumo { font-size:15.5px; line-height:1.65; color:#d3dae2; margin:0 0 16px; }
  .acoes { display:flex; gap:10px; flex-wrap:wrap; }
  .botao { background:var(--destaque); color:#0d1014; text-decoration:none; font-weight:700;
           padding:9px 16px; border-radius:8px; border:0; cursor:pointer; }
  .botao.sec { background:transparent; color:var(--txt); border:1px solid var(--borda); font-weight:600; }

  .item.lido:not(.aberto) .cabeca { opacity:.5; }
  .item.lido:not(.aberto):hover .cabeca { opacity:.85; }
  .vazio-msg { color:var(--sub); text-align:center; margin:80px 0; }
  .dica { color:var(--sub); font-size:12px; text-align:center; margin-top:30px; }
  kbd { background:var(--card2); border:1px solid var(--borda); border-radius:4px; padding:0 5px; font-size:11px; }
  #aviso { position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:var(--txt); color:var(--bg);
           padding:8px 16px; border-radius:8px; font-weight:600; opacity:0; transition:opacity .2s; pointer-events:none; }
  #aviso.visivel { opacity:1; }

  @media (max-width:700px) {
    .cabeca { flex-direction:column; }
    .capa { width:100%; }
    .seta { display:none; }
    .detalhe { padding:0 14px 16px; }
  }
</style>
</head>
<body>
<header>
  <div class="barra">
    <h1>📡 Faro <small style="color:var(--sub);font-weight:500;font-size:13px">radar tech do time</small></h1>
    <input id="busca" type="search" placeholder="Buscar (ex.: redis, mcp, playwright)…  ( / )" autocomplete="off">
    <select id="ordem">
      <option value="relevancia">Mais relevantes</option>
      <option value="recentes">Mais recentes</option>
    </select>
    <select id="fonte"><option value="">Todas as fontes</option></select>
  </div>
  <div class="chips" id="chips"></div>
</header>
<main>
  <div id="lista"></div>
  <p class="dica"><kbd>J</kbd> <kbd>K</kbd> próximo / anterior · <kbd>Enter</kbd> abre/fecha ·
     <kbd>O</kbd> abre o link · <kbd>C</kbd> copia para o time · <kbd>/</kbd> busca</p>
</main>
<div id="aviso"></div>

<script id="dados" type="application/json">__DADOS__</script>
<script>
const { noticias, gerado, erros, notaDestaque, notaValeOlhar } = JSON.parse(document.getElementById('dados').textContent);
const $ = id => document.getElementById(id);
const semAcento = s => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
const COR = c => `var(--${semAcento(c).replace(/[^A-Za-z]/g, '')})`;  // "Banco de dados" -> --Bancodedados
const urlSegura = u => /^https?:\/\//i.test(u || '') ? u : '';

// ---------- Datas em português ----------
const DIAS = ['domingo','segunda-feira','terça-feira','quarta-feira','quinta-feira','sexta-feira','sábado'];
const MESES = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
const meiaNoite = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

function nomeDoDia(ts) {
  if (!ts) return 'Sem data';
  const d = new Date(ts * 1000);
  const dif = Math.round((meiaNoite(new Date()) - meiaNoite(d)) / 86400000);
  if (dif <= 0) return 'Hoje';
  if (dif === 1) return 'Ontem';
  if (dif < 7) return DIAS[d.getDay()];
  return `${d.getDate()} de ${MESES[d.getMonth()]}`;
}

function horario(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const min = Math.floor((Date.now() - d) / 60000);
  if (min < 1) return 'agora';
  if (min < 60) return `há ${min} min`;
  if (min < 24 * 60) return `há ${Math.floor(min / 60)} h`;
  const dias = Math.floor(min / 1440);
  return dias === 1 ? 'ontem' : `há ${dias} dias`;
}

// ---------- Estado ----------
const LIDOS = 'tech-news-lidos';
const lidos = new Set(JSON.parse(localStorage.getItem(LIDOS) || '[]'));
let categoria = '', visiveis = [], atual = -1;

noticias.forEach(n => {
  n.busca = semAcento([n.titulo, n.titulo_original, n.resumo, n.fonte, n.categoria, ...n.rotulos].join(' ').toLowerCase());
});

// ---------- Chips: Todas, Destaques e categorias ----------
function criarChip(cat, rotulo, qtd, cor) {
  const b = document.createElement('button');
  b.className = 'chip' + (cat === '' ? ' ativo' : '');
  if (cor) b.style.setProperty('--cor', cor);
  b.innerHTML = '<span class="bolinha"></span><span></span><span class="qtd"></span>';
  b.children[1].textContent = rotulo;
  b.children[2].textContent = qtd;
  b.addEventListener('click', () => {
    document.querySelectorAll('.chip').forEach(c => c.classList.toggle('ativo', c === b));
    categoria = cat;
    renderizar();
  });
  $('chips').appendChild(b);
}
const porCat = {};
noticias.forEach(n => porCat[n.categoria] = (porCat[n.categoria] || 0) + 1);
criarChip('', 'Todas', noticias.length);
criarChip('*', '⭐ Destaques', noticias.filter(n => n.nota >= notaDestaque).length, 'var(--ouro)');
Object.entries(porCat).sort((a, b) => b[1] - a[1]).forEach(([c, q]) => criarChip(c, c, q, COR(c)));
const status = document.createElement('span');
status.className = 'status';
status.textContent = `atualizado ${horario(gerado) || 'agora'}`;
if (erros.length) {
  const e = document.createElement('span');
  e.className = 'erro';
  e.textContent = ` · sem resposta: ${erros.join(', ')}`;
  status.appendChild(e);
}
$('chips').appendChild(status);

[...new Set(noticias.map(n => n.fonte))].sort().forEach(f => {
  const o = document.createElement('option');
  o.textContent = f;
  $('fonte').appendChild(o);
});

// ---------- Montagem das linhas ----------
function iniciais(fonte) {
  return (fonte.match(/[A-Za-z0-9]+/g) || ['?']).slice(0, 2).map(p => p[0]).join('').toUpperCase();
}

function preencherCapa(el, n) {
  const sem = document.createElement('div');
  sem.className = 'sem';
  sem.textContent = iniciais(n.fonte);
  el.appendChild(sem);
  const src = urlSegura(n.imagem);
  if (src) {
    const img = new Image();
    img.loading = 'lazy';
    img.alt = '';
    img.referrerPolicy = 'no-referrer';
    img.onerror = () => img.remove();   // imagem quebrada: fica o quadro com as iniciais
    img.src = src;
    el.appendChild(img);
  }
}

function criarLinha(n, indice) {
  const item = document.createElement('article');
  item.className = 'item' + (lidos.has(n.link) ? ' lido' : '');
  item.style.setProperty('--cor', COR(n.categoria));
  item.innerHTML = `
    <div class="cabeca" tabindex="0" role="button" aria-expanded="false">
      <div class="capa"></div>
      <div class="texto">
        <div class="meta"><span class="tag"></span><span class="fonte"></span><span>·</span><time></time></div>
        <h3></h3>
        <p class="previa"></p>
        <div class="rotulos"></div>
      </div>
      <span class="seta">⌄</span>
    </div>
    <div class="detalhe">
      <p class="original"></p>
      <p class="resumo"></p>
      <div class="acoes">
        <a class="botao" target="_blank" rel="noopener noreferrer"></a>
        <button class="botao sec copiar">Copiar para o time</button>
        <button class="botao sec recolher">Recolher</button>
      </div>
    </div>`;
  // Todo texto vindo dos feeds entra por textContent: nunca é interpretado como HTML.
  preencherCapa(item.querySelector('.capa'), n);
  item.querySelector('.tag').textContent = n.categoria;
  item.querySelector('.fonte').textContent = n.fonte;
  item.querySelector('time').textContent = n.selo || horario(n.ts) || 'sem data';
  if (n.nota >= notaDestaque) {
    const s = document.createElement('span');
    s.className = 'estrela';
    s.textContent = '⭐ destaque';
    item.querySelector('.meta').appendChild(s);
  }
  item.querySelector('h3').textContent = n.titulo;
  item.querySelector('.previa').textContent = n.resumo;
  const rot = item.querySelector('.rotulos');
  n.rotulos.forEach(r => { const s = document.createElement('span'); s.textContent = r; rot.appendChild(s); });
  item.querySelector('.resumo').textContent = n.resumo || 'O feed não trouxe resumo para este item.';
  const original = item.querySelector('.original');
  if (n.titulo_original) original.textContent = 'Título original: ' + n.titulo_original;
  else original.remove();
  const link = item.querySelector('a.botao');
  link.href = urlSegura(n.link) || '#';
  link.textContent = n.github ? 'Abrir no GitHub ↗' : 'Ler matéria completa ↗';

  const cabeca = item.querySelector('.cabeca');
  cabeca.addEventListener('click', () => alternar(indice));
  cabeca.addEventListener('focus', () => atual = indice);
  item.querySelector('.recolher').addEventListener('click', () => alternar(indice));
  item.querySelector('.copiar').addEventListener('click', () => copiar(indice));
  n.el = item;
  return item;
}

// ---------- Lista: filtros, ordenação e agrupamento ----------
function faixa(n) {
  if (n.nota >= notaDestaque) return 'Destaques para o time';
  if (n.nota >= notaValeOlhar) return 'Vale olhar';
  return 'Outros';
}

function renderizar() {
  const termos = semAcento($('busca').value.toLowerCase()).split(/\s+/).filter(Boolean);
  const fonte = $('fonte').value;
  const porRelevancia = $('ordem').value === 'relevancia';
  visiveis = noticias.filter(n => (!categoria || (categoria === '*' ? n.nota >= notaDestaque : n.categoria === categoria))
                               && (!fonte || n.fonte === fonte)
                               && termos.every(t => n.busca.includes(t)));
  visiveis.sort(porRelevancia ? (a, b) => b.nota - a.nota || b.ts - a.ts : (a, b) => b.ts - a.ts);

  const lista = $('lista');
  lista.textContent = '';
  if (!visiveis.length) {
    lista.innerHTML = '<p class="vazio-msg">Nada com esse filtro.</p>';
    return;
  }
  const grupoDe = porRelevancia ? faixa : n => nomeDoDia(n.ts);
  let grupoAtual = null;
  visiveis.forEach((n, i) => {
    const g = grupoDe(n);
    if (g !== grupoAtual) {
      grupoAtual = g;
      const qtd = visiveis.filter(m => grupoDe(m) === g).length;
      const h = document.createElement('h2');
      h.className = 'grupo';
      h.innerHTML = '<b></b><span></span>';
      h.firstChild.textContent = g;
      h.lastChild.textContent = qtd + (qtd === 1 ? ' item' : ' itens');
      lista.appendChild(h);
    }
    lista.appendChild(criarLinha(n, i));
  });
  atual = -1;
}

// ---------- Abrir/fechar, foco e copiar ----------
function alternar(i) {
  const n = visiveis[i];
  if (!n) return;
  const abrir = !n.el.classList.contains('aberto');
  document.querySelectorAll('.item.aberto').forEach(el => {
    el.classList.remove('aberto');
    el.querySelector('.cabeca').setAttribute('aria-expanded', 'false');
  });
  if (abrir) {
    n.el.classList.add('aberto', 'lido');
    n.el.querySelector('.cabeca').setAttribute('aria-expanded', 'true');
    lidos.add(n.link);  // lido fica salvo no navegador
    localStorage.setItem(LIDOS, JSON.stringify([...lidos].slice(-3000)));
  }
  focar(i);
}

function focar(i) {
  const n = visiveis[i];
  if (!n) return;
  atual = i;
  n.el.querySelector('.cabeca').focus({ preventScroll: true });
  const topo = document.querySelector('header').offsetHeight + 12;  // não esconder atrás do topo fixo
  const r = n.el.getBoundingClientRect();
  if (r.top < topo || r.bottom > innerHeight) scrollBy({ top: r.top - topo, behavior: 'smooth' });
}

function avisar(texto) {
  $('aviso').textContent = texto;
  $('aviso').classList.add('visivel');
  setTimeout(() => $('aviso').classList.remove('visivel'), 1800);
}

// Texto pronto para colar no chat do time.
function copiar(i) {
  const n = visiveis[i];
  if (!n) return;
  const resumo = n.resumo.length > 280 ? n.resumo.slice(0, 280).replace(/\s+\S*$/, '') + '…' : n.resumo;
  const texto = `*${n.titulo}*${n.rotulos.length ? ' (' + n.rotulos.join(', ') + ')' : ''}\n${resumo}\n${n.link}`;
  navigator.clipboard.writeText(texto)
    .then(() => avisar('Copiado! Cole no chat do time.'))
    .catch(() => avisar('Não consegui copiar (permissão do navegador).'));
}

$('busca').addEventListener('input', renderizar);
$('fonte').addEventListener('change', renderizar);
$('ordem').addEventListener('change', renderizar);

document.addEventListener('keydown', ev => {
  const digitando = ['INPUT', 'SELECT'].includes(document.activeElement.tagName);
  if (ev.key === 'Escape') {
    if (digitando) document.activeElement.blur();
    else if (visiveis[atual]?.el.classList.contains('aberto')) alternar(atual);
    return;
  }
  if (digitando || ev.ctrlKey || ev.altKey || ev.metaKey) return;
  const tecla = ev.key.toLowerCase();
  if (tecla === '/') $('busca').focus();
  else if (tecla === 'j') focar(atual + 1);
  else if (tecla === 'k') focar(Math.max(atual - 1, 0));
  else if ((tecla === 'enter' || tecla === ' ') && document.activeElement.classList.contains('cabeca')) alternar(atual);
  else if (tecla === 'o' && visiveis[atual]) window.open(urlSegura(visiveis[atual].link), '_blank', 'noopener');
  else if (tecla === 'c' && visiveis[atual]) copiar(atual);
  else return;
  ev.preventDefault();
});

renderizar();
</script>
</body>
</html>"""


def gerar_html(noticias: list, erros: list) -> str:
    campos = ("titulo", "titulo_original", "resumo", "link", "imagem", "fonte", "categoria",
              "nota", "rotulos", "github", "selo", "ts")
    dados = {
        "noticias": [{c: n[c] for c in campos} for n in noticias],
        "gerado": time.time(),
        "erros": erros,
        "notaDestaque": NOTA_DESTAQUE,
        "notaValeOlhar": NOTA_VALE_OLHAR,
    }
    # "</" escapado para o conteúdo dos feeds nunca fechar a tag <script> antes da hora.
    json_seguro = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
    return MODELO_HTML.replace("__DADOS__", json_seguro)

# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Faro — radar local de tecnologia para o time de desenvolvimento.")
    ap.add_argument("--max", type=int, default=20, help="máximo de itens por fonte (padrão 20)")
    ap.add_argument("--dias", type=int, default=21, help="ignora itens mais velhos que N dias (padrão 21)")
    ap.add_argument("--out", type=Path, default=SAIDA_PADRAO, help=f"arquivo HTML (padrão {SAIDA_PADRAO})")
    ap.add_argument("--no-open", action="store_true", help="não abrir o navegador")
    ap.add_argument("--sem-capa", action="store_true",
                    help="não buscar imagem de capa nas páginas (só usa as imagens do feed; mais rápido)")
    ap.add_argument("--sem-traducao", action="store_true", help="não traduzir as fontes estrangeiras")
    args = ap.parse_args()

    inicio = time.time()
    print(f"Baixando {len(FEEDS)} feeds…")
    noticias, erros = coletar(args.max, args.dias)
    if not noticias:
        sys.exit("Nenhum item baixado. Verifique a conexão.")

    # Capa e tradução são independentes: rodam ao mesmo tempo.
    with ThreadPoolExecutor(max_workers=2) as pool:
        tarefas = []
        if not args.sem_capa:
            tarefas.append(pool.submit(completar_imagens, noticias))
        if not args.sem_traducao:
            tarefas.append(pool.submit(traduzir_noticias, noticias))
        for t in tarefas:
            t.result()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(gerar_html(noticias, erros), encoding="utf-8")
    destaques = sum(1 for n in noticias if n["nota"] >= NOTA_DESTAQUE)
    print(f"{len(noticias)} itens ({destaques} destaques) em {time.time() - inicio:.1f}s → {args.out}")

    if not args.no_open:
        webbrowser.open(args.out.resolve().as_uri())


if __name__ == "__main__":
    main()
