#!/usr/bin/env python3
"""Genera las páginas legales de la landing desde docs/*.md.

    python landing/build_docs.py           # escribe landing/es/{terminos,privacidad,reembolsos}/
    python landing/build_docs.py --check   # solo verifica, no escribe

El HTML generado se commitea: el deploy sigue siendo `git pull` + copiar
`landing/`, sin build step en el servidor. Correr esto después de editar
cualquier docs/*.md.

El markdown de docs/ usa un subconjunto acotado (encabezados, listas,
negrita, links, código inline) — por eso el convertidor son 40 líneas de
stdlib y no una dependencia nueva.

El navbar y el footer se recortan de index.html en cada corrida: una sola
copia de esos bloques en el repo.

También sella el cache-busting de style.css y script.js (ver `stamp`), por eso
hay que correrlo después de tocar esos archivos, no solo docs/*.md. El
`--check` de CI falla si quedaron desincronizados.
"""

import functools
import hashlib
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"
DOCS = ROOT / "docs"

# Las descripciones del índice no salen del markdown (no existen ahí): se
# escriben acá, una línea por sección, en el mismo orden del documento.
PAGES = [
    {
        "slug": "terminos",
        "src": "TERMS.md",
        "meta": "Condiciones del servicio de Purgito: uso aceptable, licencia, "
        "contenido generado, suscripciones y límites de responsabilidad.",
        "toc": [
            "Qué se puede y qué no se puede hacer con el bot.",
            "Licencia MIT y ausencia de garantías sobre el software.",
            "Qué implica que el texto lo genere una máquina y quién modera.",
            "Premium, precios, prueba gratuita, cancelación y reembolsos.",
            "El servicio se ofrece sin garantía de disponibilidad continua.",
            "Qué daños no cubre el desarrollador.",
            "Cómo y cuándo cambian estos Términos.",
            "Dónde escribir si tienes dudas o quieres reportar un problema.",
        ],
    },
    {
        "slug": "privacidad",
        "src": "PRIVACY.md",
        "meta": "Qué datos recopila Purgito, para qué los usa, con qué servicios "
        "los comparte y cómo eliminarlos.",
        "toc": [
            "Qué datos guarda el bot: IDs, mensajes, multimedia, sesión y pagos.",
            "Para qué se usan esos datos — nunca para publicidad ni venta.",
            "Proveedores externos que intervienen en alguna función.",
            "Cuánto tiempo se conservan los datos y cómo borrarlos.",
            "Qué puedes pedir sobre la información recopilada.",
            "Edad mínima y capacidad para contratar premium.",
            "Medidas para proteger la información almacenada.",
            "Cómo se avisan las actualizaciones de esta Política.",
            "Dónde escribir para preguntar o pedir una eliminación.",
        ],
    },
    {
        "slug": "reembolsos",
        "src": "REFUNDS.md",
        "meta": "Política de reembolsos de las suscripciones premium de Purgito.",
        "toc": [
            "La prueba gratuita de 7 días y sus condiciones.",
            "Cómo cancelar la suscripción desde el portal de Polar.",
            "Por qué no se ofrecen reembolsos por el período ya pagado.",
            "Cuándo se puede revocar el acceso premium.",
            "Qué pasa con tu contenido guardado si el servidor pierde Premium.",
            "A quién queda asociado el premium: al servidor, no a la cuenta.",
        ],
    },
]

# Páginas que no salen de un markdown: el cuerpo se escribe a mano en
# landing/pages/ y acá solo se le pega el navbar/footer/head compartido.
#
# "app" marca las páginas del dashboard: además del <head> común les suma
# dash.css y su módulo de entrada. Son las únicas que cargan JavaScript propio
# — el resto del sitio se sirve con script.js y nada más.
HTML_PAGES = [
    {
        "slug": "premium",
        "src": "premium.html",
        "title": "Purgito Premium",
        "meta": "Apoya a Purgito y obtén beneficios exclusivos: más memoria, "
        "más GIFs, memes automáticos y plantillas de embeds.",
    },
    {
        "slug": "perfil",
        "src": "perfil.html",
        "title": "Tu perfil",
        "meta": "Tus servidores de Discord con Purgito: entra al dashboard de "
        "cada uno o invítalo a los que falten.",
        "app": "perfil.js",
    },
    # Mismo cuerpo que /es/perfil: perfil.js decide la tab por la URL. Existen
    # como páginas propias para que cada una tenga su título y su link real.
    {
        "slug": "perfil/conexiones",
        "src": "perfil.html",
        "title": "Conexiones",
        "meta": "Conexiones de tu cuenta de Purgito.",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/facturacion",
        "src": "perfil.html",
        "title": "Facturación",
        "meta": "Estado de tus suscripciones Premium de Purgito.",
        "app": "perfil.js",
    },
    {
        "slug": "dashboard",
        "src": "dashboard.html",
        "title": "Dashboard",
        "meta": "Configura Purgito en tu servidor: chat, corpus, reacciones, "
        "frases, GIFs, embeds y premium.",
        "app": "dash.js",
    },
    {
        "slug": "estado",
        "src": "estado.html",
        "title": "Estado de Purgito",
        "meta": "Estado en vivo de Purgito: tiempo activo, memoria, latencia "
        "con Discord y cantidad de servidores. Pública, sin necesidad de login.",
        "module": "estado.js",
    },
    {
        "slug": "documentacion",
        "src": "documentacion/index.html",
        "title": "Documentación técnica",
        "meta": "Documentación técnica sobre la arquitectura, APIs, sistemas "
        "internos e infraestructura de Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/arquitectura",
        "src": "documentacion/arquitectura.html",
        "title": "Arquitectura — Documentación técnica",
        "meta": "Cómo se conectan el bot de Discord, el motor de generación, "
        "la base de datos y el dashboard de Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/discord",
        "src": "documentacion/discord.html",
        "title": "Discord — Documentación técnica",
        "meta": "Cogs, eventos, permisos e interacciones del bot de Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/api",
        "src": "documentacion/api.html",
        "title": "API — Documentación técnica",
        "meta": "Autenticación, sesiones, endpoints y webhooks de la API de Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/generacion",
        "src": "documentacion/generacion.html",
        "title": "Motor de generación — Documentación técnica",
        "meta": "Cómo genera texto Purgito: cadenas de Markov, corpus, "
        "concurrencia y límites.",
        "doc": True,
    },
    {
        "slug": "documentacion/almacenamiento",
        "src": "documentacion/almacenamiento.html",
        "title": "Almacenamiento — Documentación técnica",
        "meta": "SQLite, Cloudflare R2, cachés en memoria y retención de "
        "datos en Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/seguridad",
        "src": "documentacion/seguridad.html",
        "title": "Seguridad — Documentación técnica",
        "meta": "Modelo de seguridad de Purgito: OAuth2, sesiones, permisos "
        "y límites de uso.",
        "doc": True,
    },
    {
        "slug": "documentacion/infraestructura",
        "src": "documentacion/infraestructura.html",
        "title": "Infraestructura — Documentación técnica",
        "meta": "Runtime, nginx, Cloudflare y despliegue de Purgito en producción.",
        "doc": True,
    },
    {
        "slug": "documentacion/desarrollo",
        "src": "documentacion/desarrollo.html",
        "title": "Desarrollo — Documentación técnica",
        "meta": "Estructura del proyecto, entorno local y tests de Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/referencia",
        "src": "documentacion/referencia.html",
        "title": "Referencia — Documentación técnica",
        "meta": "Variables de entorno de Purgito.",
        "doc": True,
    },
]

# Estructura de /es/documentacion: una entrada por página. Los "subs" son
# anclas dentro de esa misma página (no páginas propias) — ver Task 1 del
# plan de documentación técnica para el porqué de la granularidad agrupada.
DOC_SECTIONS = [
    {"slug": "documentacion", "label": "Inicio", "subs": []},
    {
        "slug": "documentacion/arquitectura",
        "label": "Arquitectura",
        "subs": [
            ("vision-general", "Visión general"),
            ("componentes", "Componentes"),
            ("flujo-de-una-peticion", "Flujo de una petición"),
        ],
    },
    {
        "slug": "documentacion/discord",
        "label": "Discord",
        "subs": [
            ("bot-y-cogs", "Bot y cogs"),
            ("eventos", "Eventos"),
            ("permisos", "Permisos"),
            ("interacciones", "Interacciones"),
        ],
    },
    {
        "slug": "documentacion/api",
        "label": "API",
        "subs": [
            ("vision-general", "Visión general"),
            ("autenticacion", "Autenticación"),
            ("sesiones", "Sesiones"),
            ("endpoints", "Endpoints"),
            ("webhooks", "Webhooks"),
        ],
    },
    {
        "slug": "documentacion/generacion",
        "label": "Generación",
        "subs": [
            ("motor-markov", "Motor de Markov"),
            ("corpus", "Corpus"),
            ("pipeline", "Pipeline de generación"),
            ("concurrencia-y-limites", "Concurrencia y límites"),
        ],
    },
    {
        "slug": "documentacion/almacenamiento",
        "label": "Almacenamiento",
        "subs": [
            ("sqlite", "SQLite"),
            ("r2", "R2"),
            ("cache", "Caché"),
            ("retencion", "Retención de datos"),
        ],
    },
    {
        "slug": "documentacion/seguridad",
        "label": "Seguridad",
        "subs": [
            ("oauth2", "OAuth2"),
            ("permisos", "Permisos"),
            ("rate-limits", "Límites de uso"),
            ("modelo-de-seguridad", "Modelo de seguridad"),
        ],
    },
    {
        "slug": "documentacion/infraestructura",
        "label": "Infraestructura",
        "subs": [
            ("runtime", "Runtime"),
            ("nginx", "Nginx"),
            ("cloudflare", "Cloudflare"),
            ("deployment", "Despliegue"),
            ("health-checks", "Chequeos de salud"),
        ],
    },
    {
        "slug": "documentacion/desarrollo",
        "label": "Desarrollo",
        "subs": [
            ("estructura-del-proyecto", "Estructura del proyecto"),
            ("entorno-local", "Entorno local"),
            ("tests", "Tests"),
        ],
    },
    {
        "slug": "documentacion/referencia",
        "label": "Referencia",
        "subs": [
            ("variables-de-entorno", "Variables de entorno"),
        ],
    },
]


def doc_sidebar(current_slug):
    """Sidebar de /es/documentacion: categorías + anclas de la página activa.

    Sin JS: la categoría activa se resuelve en build time (cada página sabe
    su propio slug) y las anclas son <a href="#id"> normales.
    """
    items = []
    for sec in DOC_SECTIONS:
        active = sec["slug"] == current_slug
        cls = ' class="active"' if active else ""
        href = "/es/%s" % sec["slug"]
        items.append(
            '    <li><a%s href="%s">%s</a>' % (cls, href, html.escape(sec["label"]))
        )
        if active and sec["subs"]:
            sub_items = "".join(
                '<li><a href="#%s">%s</a></li>' % (anchor, html.escape(label))
                for anchor, label in sec["subs"]
            )
            items.append('      <ul class="docs-subnav">%s</ul>' % sub_items)
        items.append("    </li>")
    return (
        '<details class="docs-sidebar" open aria-label="Documentación técnica">\n'
        "  <summary>Categorías</summary>\n"
        "  <ul>\n%s\n  </ul>\n</details>" % "\n".join(items)
    )


# ── markdown → html ──────────────────────────────────────────────────────────


def inline(text):
    """`code`, **negrita** y [texto](url) sobre texto ya escapado."""
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r'<code class="cmd">\1</code>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        out,
    )
    return out


def render(body):
    """Cuerpo de una sección → HTML. Agrupa listas y párrafos multilínea."""
    out, para, items = [], [], []

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()
        if items:
            out.append(
                "<ul>" + "".join("<li>%s</li>" % inline(i) for i in items) + "</ul>"
            )
            items.clear()

    for line in body.splitlines():
        line = line.strip()
        if not line or line == "---":
            flush()
        elif line.startswith("## "):
            flush()
            out.append("<h3>%s</h3>" % inline(line[3:]))
        elif line.startswith("- "):
            if para:
                flush()
            items.append(line[2:])
        elif items:
            # Bullet cortado en varias líneas: sigue el ítem, no abre párrafo.
            items[-1] += " " + line
        else:
            para.append(line)
    flush()
    return "\n".join(out)


def parse(md):
    """Devuelve (título, fecha, intro_html, [(encabezado, cuerpo_html), …]).

    Los `# ` de nivel 1 separan: el primero es el título del documento y los
    siguientes son las secciones numeradas. Un documento sin secciones de
    nivel 1 (REFUNDS) usa sus `## ` como secciones.
    """
    chunks = re.split(r"^# ", md, flags=re.M)[1:]
    head, rest = chunks[0], chunks[1:]
    if not rest:
        head, *rest = re.split(r"^## ", head, flags=re.M)

    title, _, intro = head.partition("\n")
    date = re.search(r"\*\*Última actualización:\*\*\s*(.+)", intro)
    intro = re.sub(r"^\*\*Última actualización:\*\*.*$", "", intro, flags=re.M)

    sections = []
    for chunk in rest:
        name, _, body = chunk.partition("\n")
        sections.append((name.strip(), render(body)))
    return title.strip(), date.group(1).strip() if date else "", render(intro), sections


# ── página ───────────────────────────────────────────────────────────────────

# Cubre lo que el sitio realmente carga: fonts.googleapis.com/gstatic.com
# (@import de fuentes en style.css), tenor.com (iframe de preview de GIFs en
# la tab de gifs del dashboard), img-src ancho porque las imágenes salen de
# hosts variables según guild (avatares e emojis de Discord, GIFs de Giphy,
# el bucket R2 configurado por env var). El primer hash cubre el único
# inline handler que hay en todo el sitio (onerror="this.remove()" en los
# <img> del navbar/botones de invitar); el segundo cubre el <script> inline
# de redirect de idioma que solo vive en index.html (tiene que ir en el
# <head>, antes de pintar nada, así que no puede ser /script.js externo) --
# ambos sin abrir 'unsafe-inline'. meta http-equiv NO soporta
# frame-ancestors/sandbox/report-uri -- la protección contra clickjacking
# para estas páginas va por X-Frame-Options: DENY, que sí pone nginx como
# cabecera real (ver DEPLOY.md); no hay una CSP con frame-ancestors a nivel
# nginx (a propósito: se pisaría con esta CSP y con la de la API, ver el
# comentario del add_header en DEPLOY.md).
LANDING_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'sha256-9f8ZK5epjuMsYtXFjPqrgJI0L4QOAUYmJdHtT+RSH/c=' "
    "'sha256-XZdqffSf7TZ1Kkoli0wRvKdpWxXleEGmPL6IIIcj0O4='; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' https: data:; "
    "frame-src https://tenor.com; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

SHELL = (
    """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="%s">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Purgito</title>
<meta name="description" content="{meta}">
<meta name="theme-color" content="#13c4d8">
<link rel="icon" href="/assets/icon.png">
<link rel="stylesheet" href="/style.css">
{head}</head>
<body>

<div id="bg" class="bg-short" aria-hidden="true"></div>

<a class="skip" href="#contenido">Saltar al contenido</a>

{nav}

{body}

{footer}

<script src="/script.js"></script>
{scripts}</body>
</html>
"""
    % LANDING_CSP
)

# Páginas del dashboard: el CSS propio va después de style.css (lo extiende, no
# lo reemplaza) y el módulo de entrada después de script.js, que es quien pinta
# la sesión en el navbar.
APP_HEAD = '<link rel="stylesheet" href="/dash.css">\n{importmap}'
APP_SCRIPT = '<script type="module" src="/js/{src}?v={v}"></script>\n'
# Páginas públicas con un módulo ES propio (ej. /es/estado) pero SIN dash.css:
# no son parte del dashboard, así que no necesitan su hoja de estilos, pero sí
# el importmap para que el cache-busting de Cloudflare alcance a lo que ese
# módulo importa (mismo motivo que las páginas "app" -- ver import_map()).
MODULE_HEAD = "{importmap}"


def build_toc(sections, descs):
    if not sections:
        return ""
    rows = []
    for i, ((name, _), desc) in enumerate(zip(sections, descs), 1):
        rows.append(
            '      <li><a href="#seccion-%d"><span class="toc-t">%s</span>'
            '<span class="toc-d">%s</span></a></li>' % (i, html.escape(name), desc)
        )
    return (
        '  <nav class="box doc-toc" aria-labelledby="indice">\n'
        '    <h2 id="indice">Índice</h2>\n'
        "    <ol>\n%s\n    </ol>\n  </nav>\n" % "\n".join(rows)
    )


def build_page(page, nav, footer):
    title, date, intro, sections = parse((DOCS / page["src"]).read_text("utf-8"))
    descs = page["toc"]
    if len(descs) != len(sections):
        sys.exit(
            "%s: %d secciones en el markdown pero %d descripciones en PAGES"
            % (page["src"], len(sections), len(descs))
        )

    blocks = []
    for i, (name, body) in enumerate(sections, 1):
        blocks.append(
            '  <section class="box doc-sec" id="seccion-%d">\n'
            '    <h2 class="doc-sec-title">%s</h2>\n'
            '    <div class="doc-body">\n%s\n    </div>\n  </section>'
            % (i, html.escape(name), body)
        )

    body = (
        '<main id="contenido" class="doc wrap">\n'
        '  <header class="doc-head">\n'
        '    <h1 class="doc-title">%s</h1>\n'
        '    <p class="doc-date">Última actualización: %s</p>\n'
        '    <div class="doc-body doc-intro">\n%s\n    </div>\n'
        "  </header>\n%s%s\n</main>"
        % (
            html.escape(title),
            html.escape(date),
            intro,
            build_toc(sections, descs),
            "\n".join(blocks),
        )
    )
    return SHELL.format(
        title=html.escape(title),
        meta=html.escape(page["meta"]),
        nav=nav,
        body=body,
        footer=footer,
        head="",
        scripts="",
    )


def build_html_page(page, nav, footer):
    """Página con cuerpo escrito a mano (landing/pages/*.html).

    Solo aporta el navbar, el footer y el <head> — el resto sale del archivo
    tal cual. Existe para que esas piezas no se dupliquen fuera de index.html.
    Las que traen "app" suman además dash.css y su módulo de entrada; las que
    traen "module" suman el módulo pero NO dash.css (páginas públicas con su
    propio JS, ej. /es/estado, que no son parte del dashboard). Las que traen
    "doc" son de /es/documentacion: se envuelven en el sidebar de doc_sidebar().
    """
    entry = page.get("app") or page.get("module")
    if page.get("app"):
        head = APP_HEAD.format(importmap=import_map())
    elif page.get("module"):
        head = MODULE_HEAD.format(importmap=import_map())
    else:
        head = ""
    raw_body = (LANDING / "pages" / page["src"]).read_text("utf-8").strip()
    if page.get("doc"):
        raw_body = (
            '<div class="docs-shell wrap">\n%s\n'
            '  <main id="contenido" class="docs-content">\n%s\n  </main>\n</div>'
            % (doc_sidebar(page["slug"]), raw_body)
        )
    return SHELL.format(
        title=html.escape(page["title"]),
        meta=html.escape(page["meta"]),
        nav=nav,
        body=raw_body,
        footer=footer,
        head=head,
        scripts=APP_SCRIPT.format(src=entry, v=js_files()[0]) if entry else "",
    )


@functools.cache
def js_files():
    """(hash del árbol, rutas de landing/js/**.js) — un solo hash para todos.

    Tocar cualquier módulo invalida el árbol entero: es algo más de caché
    tirada a la basura, a cambio de un mapa estable y un diff mínimo. Son
    ~130 KB en total, no vale la pena afinarlo por archivo.
    """
    files = sorted((LANDING / "js").rglob("*.js"))
    digest = hashlib.sha256(
        b"".join(
            p.relative_to(LANDING).as_posix().encode() + p.read_bytes() for p in files
        )
    ).hexdigest()[:8]
    return digest, files


def import_map():
    """`<script type="importmap">` que le pone ?v= a cada módulo de landing/js/.

    Sin esto el cache-busting del dashboard quedaría a medias: el `?v=` del
    <script> de entrada no se propaga a lo que ese módulo importa, y Cloudflare
    (4 h de caché para .js) seguiría sirviendo los módulos internos viejos
    después de un deploy — el bug clásico de "actualicé y no cambió nada".

    Las claves son las mismas rutas absolutas que usan los `import` de
    landing/js/, así que el mapa es una sustitución 1:1: sin bare specifiers
    ni scopes, y los módulos siguen funcionando si el mapa no se aplica.
    """
    digest, files = js_files()
    entries = {
        "/" + p.relative_to(LANDING).as_posix(): "/%s?v=%s"
        % (p.relative_to(LANDING).as_posix(), digest)
        for p in files
    }
    return '<script type="importmap">\n%s\n</script>\n' % json.dumps(
        {"imports": entries}, indent=2, ensure_ascii=False
    )


# ── cache-busting ────────────────────────────────────────────────────────────

# Cloudflare cachea .css/.js 4 h por default (el HTML no), así que un deploy
# deja los assets viejos servidos hasta que alguien purgue a mano. El hash del
# contenido en el query string hace que cada cambio sea una URL nueva.
ASSETS = ("style.css", "script.js", "dash.css")


def stamp(page_html):
    """`/style.css` → `/style.css?v=<hash8>`, con el hash del archivo real.

    Idempotente: un `?v=` viejo se reemplaza en vez de acumularse. Hash del
    contenido y no mtime, que cambia en cada clone y ensuciaría el diff.
    """
    for name in ASSETS:
        digest = hashlib.sha256((LANDING / name).read_bytes()).hexdigest()[:8]
        page_html = re.sub(
            r'(?<=["\'])/%s(?:\?v=[0-9a-f]+)?(?=["\'])' % re.escape(name),
            "/%s?v=%s" % (name, digest),
            page_html,
        )
    return page_html


def chunk_of(src, pattern):
    m = re.search(pattern, src, re.S)
    if not m:
        sys.exit("no encontré %r en index.html" % pattern)
    return m.group(0)


def main():
    index_path = LANDING / "index.html"
    index = index_path.read_text("utf-8")
    nav = chunk_of(index, r'<nav class="nav" id="top">.*?\n</nav>')
    footer = chunk_of(index, r'<footer class="footer">.*?</footer>')
    check = "--check" in sys.argv

    # index.html se escribe a mano: no se regenera, solo se le resella el ?v=.
    stamped_index = stamp(index)
    if stamped_index != index:
        if check:
            sys.exit(
                "%s tiene el ?v= desactualizado — corre build_docs.py" % index_path
            )
        index_path.write_text(stamped_index, "utf-8")
        print("→", index_path.relative_to(ROOT))

    todo = [(p, build_page) for p in PAGES] + [(p, build_html_page) for p in HTML_PAGES]
    for page, build in todo:
        out = LANDING / "es" / page["slug"] / "index.html"
        page_html = stamp(build(page, nav, footer))
        if check:
            if not out.exists() or out.read_text("utf-8") != page_html:
                sys.exit("%s está desactualizado — corre build_docs.py" % out)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(page_html, "utf-8")
            print("→", out.relative_to(ROOT))

    # Self-check del parser: el formato de docs/*.md es la única entrada, así
    # que si cambia (o el convertidor se rompe) esto falla acá y no en prod.
    title, date, intro, sections = parse((DOCS / "TERMS.md").read_text("utf-8"))
    assert title == "Condiciones del Servicio (Terms of Service)", title
    assert date == "12 de julio de 2026", date
    assert "<p>" in intro and "Última actualización" not in intro, intro
    assert len(sections) == 8, len(sections)
    assert sections[0][0] == "1. Uso Aceptable"
    assert "<h3>Reembolsos</h3>" in sections[3][1]
    assert len(parse((DOCS / "PRIVACY.md").read_text("utf-8"))[3]) == 9
    # REFUNDS no tiene `# N.`: sus `## ` son las secciones.
    refunds = parse((DOCS / "REFUNDS.md").read_text("utf-8"))
    assert refunds[0] == "Políticas de reembolsos", refunds[0]
    assert refunds[1] == "2 de agosto de 2026", refunds[1]
    assert len(refunds[3]) == 6, len(refunds[3])
    assert refunds[3][0][0] == "Prueba gratuita (trial)", refunds[3][0][0]
    assert "<h3>" not in refunds[3][0][1], refunds[3][0][1]
    assert render("- uno\n  sigue") == "<ul><li>uno sigue</li></ul>", render(
        "- uno\n  sigue"
    )
    assert render("- uno\n- dos") == "<ul><li>uno</li><li>dos</li></ul>", render(
        "- uno\n- dos"
    )
    assert render("a\nb") == "<p>a b</p>", render("a\nb")
    assert '<a href="x" target="_blank" rel="noopener">t</a>' in inline("[t](x)")
    assert inline("a & <b>") == "a &amp; &lt;b&gt;", inline("a & <b>")
    # El sellado tiene que ser idempotente: sin esto, cada corrida encadenaría
    # otro ?v= y el HTML nunca convergería.
    once = stamp('<link href="/style.css"><script src="/script.js"></script>')
    assert re.search(r'/style\.css\?v=[0-9a-f]{8}"', once), once
    assert re.search(r'/script\.js\?v=[0-9a-f]{8}"', once), once
    assert stamp(once) == once, once
    assert stamp("<p>style.css sin barra</p>") == "<p>style.css sin barra</p>"
    print("ok")


if __name__ == "__main__":
    main()
