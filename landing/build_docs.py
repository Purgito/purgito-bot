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
"""

import html
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
            "A quién queda asociado el premium: al servidor, no a la cuenta.",
        ],
    },
]


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

SHELL = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Purgito</title>
<meta name="description" content="{meta}">
<meta name="theme-color" content="#13c4d8">
<link rel="icon" href="/assets/icon.png">
<link rel="stylesheet" href="/style.css">
</head>
<body>

<div id="bg" class="bg-short" aria-hidden="true"></div>

<a class="skip" href="#contenido">Saltar al contenido</a>

{nav}

<main id="contenido" class="doc wrap">
  <header class="doc-head">
    <h1 class="doc-title">{title}</h1>
    <p class="doc-date">Última actualización: {date}</p>
    <div class="doc-body doc-intro">
{intro}
    </div>
  </header>
{toc}{sections}
</main>

{footer}

<script src="/script.js"></script>
</body>
</html>
"""


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

    return SHELL.format(
        title=html.escape(title),
        meta=html.escape(page["meta"]),
        date=html.escape(date),
        nav=nav,
        intro=intro,
        toc=build_toc(sections, descs),
        sections="\n".join(blocks),
        footer=footer,
    )


def chunk_of(src, pattern):
    m = re.search(pattern, src, re.S)
    if not m:
        sys.exit("no encontré %r en index.html" % pattern)
    return m.group(0)


def main():
    index = (LANDING / "index.html").read_text("utf-8")
    nav = chunk_of(index, r'<nav class="nav" id="top">.*?\n</nav>')
    footer = chunk_of(index, r'<footer class="footer">.*?</footer>')
    check = "--check" in sys.argv

    for page in PAGES:
        out = LANDING / "es" / page["slug"] / "index.html"
        page_html = build_page(page, nav, footer)
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
    assert len(refunds[3]) == 5, len(refunds[3])
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
    print("ok")


if __name__ == "__main__":
    main()
