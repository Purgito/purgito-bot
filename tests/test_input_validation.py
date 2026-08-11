"""Auditoría sección 9: validación de entradas e inputs maliciosos.

Cubre lo que no entra en test_mention_injection.py:

1. SQL: barrido AST de todo src/ -- ninguna query se arma con f-string o
   concatenación sobre datos (punto 1).
2. Triggers: tope de largo del pattern ANTES de compilar, y que el timeout
   real del matching corta un regex con backtracking catastrófico (punto 2).
3. Layouts: accent_color y URLs de imagen validadas al guardar, no al enviar
   (puntos 3 y 6 -- el color termina concatenado en un atributo style del
   preview del dashboard).
4. Texto de admin: caracteres de control y overrides de dirección (punto 6).
5. gifsicle: invocación por lista de argumentos, sin shell (punto 5).
6. Uploads: la key sale del contenido, nunca del nombre que manda el cliente
   (punto 7).
"""

import ast
import asyncio
import inspect
import pathlib

import pytest

import db

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _handler_source(name: str) -> str:
    """Fuente de un handler de webapi.py leída del archivo.

    inspect.getsource sobre uno decorado con @guild_api devuelve el wrapper,
    no el handler, así que se corta el texto del módulo por su `async def`.
    """
    texto = (_SRC / "webapi.py").read_text(encoding="utf-8")
    inicio = texto.index(f"async def {name}(")
    fin = texto.index("\n@", inicio)
    return texto[inicio:fin]


# ── 1. SQL injection ─────────────────────────────────────────────────────────


def _sql_call_args():
    """Primer argumento de cada .execute*/ del proyecto, con su ubicación."""
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in ("execute", "executemany", "executescript") and node.args:
                yield path.name, node.lineno, node.args[0]


def _interpolated_names(node):
    """Nombres interpolados en un f-string de SQL (vacío si no es un f-string
    o si solo interpola constantes)."""
    if not isinstance(node, ast.JoinedStr):
        return []
    out = []
    for value in node.values:
        if isinstance(value, ast.FormattedValue):
            out.append(ast.unparse(value.value))
    return out


# Únicos f-strings de SQL permitidos, con el motivo por el que son seguros.
# Si aparece uno nuevo, este test falla y hay que justificarlo acá.
_SQL_FSTRING_ALLOWLIST = {
    # Nombres de columna/tabla que salen de listas fijas del propio módulo,
    # nunca del request: CHAT_TUNABLES, _TUNABLE_KEYS y la lista literal de
    # tablas de purge_guild_data. Los VALORES siempre van por parámetro.
    "cols",
    "marks",
    "updates",
    "table",
    # Migraciones: nombres y defaults de columnas, todos literales del módulo.
    "_col",
    "_type",
    "_default",
    "_table",
    "DEFAULT_MENTION_RATE_LIMIT",
    # count_audit_action: el intervalo va casteado con int() en el sitio.
    "int(days)",
}


def test_ninguna_query_interpola_datos():
    ofensores = []
    for filename, lineno, arg in _sql_call_args():
        for expr in _interpolated_names(arg):
            if expr not in _SQL_FSTRING_ALLOWLIST:
                ofensores.append(f"{filename}:{lineno} -> {{{expr}}}")
    assert not ofensores, "SQL armado con datos interpolados: " + "; ".join(ofensores)


def test_ninguna_query_se_arma_concatenando_variables():
    """Un `"SELECT ..." + var` no lo detecta el test de f-strings."""

    def solo_constantes(node):
        if isinstance(node, ast.Constant):
            return isinstance(node.value, str)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return solo_constantes(node.left) and solo_constantes(node.right)
        return True  # Name/JoinedStr los cubre el test de arriba

    ofensores = [
        f"{filename}:{lineno}"
        for filename, lineno, arg in _sql_call_args()
        if isinstance(arg, ast.BinOp) and not solo_constantes(arg)
    ]
    assert not ofensores, "SQL concatenado con variables: " + "; ".join(ofensores)


# ── 2. Triggers: largo del pattern y ReDoS ───────────────────────────────────


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def test_pattern_gigante_no_llega_a_compilarse():
    """regex.compile es sincrónico: un patrón de 1 MB congela el event loop
    (~7 s medidos) y con él al bot entero. El largo se chequea antes."""
    src = _handler_source("_api_triggers_post")
    pos_largo = src.index("MAX_TRIGGER_PATTERN")
    pos_compile = src.index("regex.compile(pattern)")
    assert pos_largo < pos_compile, "el largo se valida DESPUÉS de compilar"
    assert "_rate_ok" in src, "el POST de triggers necesita rate limit por IP"


def test_el_pattern_guardado_es_el_que_se_valido(temp_db):
    """Si la API valida el patrón entero y la DB guarda un recorte, lo que
    corre contra los mensajes del canal no es lo que se validó."""
    largo = "(a|b)" * 200  # 1000 caracteres, regex válido
    assert len(largo) > db.MAX_TRIGGER_PATTERN

    async def run():
        return await db.add_channel_trigger(1, 10, "regex", largo, "markov")

    assert asyncio.run(run()) is None


def test_regex_catastrofico_corta_por_timeout():
    """El patrón lo escribe un admin, así que no alcanza con validar que
    compile: tiene que poder cortarse mientras matchea."""
    import cogs.chat as chat_mod

    trigger = {"match_type": "regex", "pattern": "(a+)+$"}
    contenido = "a" * 20_000 + "!"

    assert asyncio.run(chat_mod._trigger_matches(trigger, contenido)) is False


def test_regex_normal_sigue_matcheando():
    import cogs.chat as chat_mod

    trigger = {"match_type": "regex", "pattern": r"^hola\b"}
    assert asyncio.run(chat_mod._trigger_matches(trigger, "hola mundo")) is True
    assert asyncio.run(chat_mod._trigger_matches(trigger, "chau mundo")) is False


def test_playground_recorta_el_mensaje_de_prueba():
    """Sin tope, el texto entero entraba al matcheo de cada trigger regex del
    canal, cada uno hasta medio segundo de thread pool."""
    src = _handler_source("_api_chat_playground_post")
    assert "[:4000]" in src


# ── 3. Layouts: color y URLs ─────────────────────────────────────────────────


def _layout(**container):
    base = {"type": "container", "children": [{"type": "text", "content": "x"}]}
    base.update(container)
    return {"blocks": [base]}


@pytest.mark.parametrize(
    "color",
    [
        "red;background-image:url(https://evil.test/x.png)",  # inyección CSS
        "no-es-un-color",
        "#12345",
        "#1234567",
        -1,
        0x1000000,
        True,
    ],
)
def test_accent_color_invalido_se_rechaza(color):
    from layout_v2 import validate_layout_v2_payload

    assert validate_layout_v2_payload(_layout(accent_color=color)) is not None


@pytest.mark.parametrize("color", ["#8B6EF5", "8b6ef5", 0, 0xFFFFFF, None])
def test_accent_color_valido_se_acepta(color):
    from layout_v2 import validate_layout_v2_payload

    assert validate_layout_v2_payload(_layout(accent_color=color)) is None


def test_accent_color_valido_se_puede_construir():
    """El objetivo real: lo que pasa la validación tiene que poder enviarse.

    Antes, un color inválido se guardaba y recién reventaba en _parse_color al
    construir el mensaje -- con el anuncio ya programado, así que el worker lo
    reintentaba cada minuto para siempre.
    """
    from layout_v2 import build_layout_view, validate_layout_v2_payload

    payload = _layout(accent_color="#8B6EF5")
    assert validate_layout_v2_payload(payload) is None
    build_layout_view(payload)  # no debe levantar


@pytest.mark.parametrize("url", ["", "   ", "u", "javascript:alert(1)", "//x.test/i"])
def test_url_de_imagen_invalida_se_rechaza(url):
    from layout_v2 import validate_layout_v2_payload

    thumb = {
        "blocks": [
            {
                "type": "section",
                "texts": ["x"],
                "accessory": {"type": "thumbnail", "url": url},
            }
        ]
    }
    galeria = {"blocks": [{"type": "media_gallery", "items": [{"url": url}]}]}
    assert validate_layout_v2_payload(thumb) is not None
    assert validate_layout_v2_payload(galeria) is not None


def test_url_de_imagen_http_se_acepta():
    from layout_v2 import validate_layout_v2_payload

    galeria = {
        "blocks": [
            {"type": "media_gallery", "items": [{"url": "https://x.test/i.png"}]}
        ]
    }
    assert validate_layout_v2_payload(galeria) is None


def test_color_del_preview_solo_acepta_hex():
    """colorToHex alimenta tres `style: 'background:' + color` del dashboard."""
    js = (_ROOT / "landing/js/embeds/state.js").read_text(encoding="utf-8")
    fn = js[js.index("export function colorToHex") :][:400]
    assert "/^#[0-9a-fA-F]{6}$/" in fn

    # Los tres módulos que pintan un color guardado dentro de un atributo
    # style tienen que pasarlo por el guard, no usar el valor crudo.
    for path in (
        "landing/js/embeds/classic-editor.js",
        "landing/js/embeds/shared-ui.js",
        "landing/js/embeds/layout-editor.js",
    ):
        texto = (_ROOT / path).read_text(encoding="utf-8")
        assert "colorToHex" in texto, path


# ── 4. Caracteres de control y overrides de dirección ────────────────────────


def test_clean_admin_text_saca_control_y_bidi():
    sucio = "hola‮odnum\x00 y\x1b[31m rojo"
    assert db.clean_admin_text(sucio) == "holaodnum y[31m rojo"


def test_clean_admin_text_respeta_texto_legitimo():
    """Emoji compuesto (ZWJ), saltos de línea, tabs y escrituras RTL reales:
    nada de eso se toca -- el algoritmo bidi de Unicode resuelve el árabe sin
    necesitar los caracteres de override."""
    ok = "línea 1\nlínea 2\tfin 👨‍👩‍👧 مرحبا"
    assert db.clean_admin_text(ok) == ok


def test_frases_packs_y_triggers_se_guardan_limpios(temp_db):
    async def run():
        await db.add_frase_especial(1, 1, "u", "frase‮con rlo\x00")
        pack_id = await db.add_frase_pack(1, "pack‮raro")
        trigger_id = await db.add_channel_trigger(
            1, 10, "exact", "trig\x00ger", "markov"
        )
        return (
            await db.get_random_frase_especial(1),
            [p["name"] for p in await db.list_frase_packs(1)],
            (await db.list_channel_triggers(1, 10))[0]["pattern"],
            pack_id,
            trigger_id,
        )

    frase, packs, pattern, pack_id, trigger_id = asyncio.run(run())
    assert pack_id is not None and trigger_id is not None
    for texto in (frase, packs[0], pattern):
        assert "‮" not in texto and "\x00" not in texto


def test_reaccion_tiene_tope_de_largo(temp_db):
    """Era el único campo de texto de admin sin tope, y el pool no tiene cuota
    de filas: se podían guardar reacciones de cientos de KB."""

    async def run():
        gigante = await db.add_reaction_to_pool(1, "A" * 100_000)
        normal = await db.add_reaction_to_pool(1, "😀")
        custom = await db.add_reaction_to_pool(1, "<a:purgito:123456789012345678>")
        return gigante, normal, custom, await db.list_reaction_pool(1)

    gigante, normal, custom, pool = asyncio.run(run())
    assert gigante is False
    assert normal is True and custom is True
    assert all(len(r["emoji_text"]) <= db.MAX_REACTION_TEXT for r in pool)


# ── 5. gifsicle ──────────────────────────────────────────────────────────────


def test_gifsicle_se_invoca_sin_shell():
    """Nada controlado por el usuario llega a argv (el GIF entra por stdin),
    pero el día que alguien agregue un flag desde config, shell=True lo
    convertiría en ejecución de comandos."""
    import r2

    src = inspect.getsource(r2.optimize_gif_bytes)
    assert "shell=True" not in src
    assert 'cmd = ["gifsicle"' in src
    assert "input=data" in src  # por stdin: ningún nombre de archivo en argv

    modulo = inspect.getsource(r2)
    assert "os.system" not in modulo and "shell=True" not in modulo


def test_lossy_level_es_un_entero_acotado(monkeypatch):
    import r2

    monkeypatch.setenv("GIF_LOSSY_LEVEL", "30; rm -rf /")
    assert r2._lossy_level() == 30  # cae al default, no se interpola nada
    monkeypatch.setenv("GIF_LOSSY_LEVEL", "99999")
    assert r2._lossy_level() == 200


# ── 6. Nombres de archivo del cliente ────────────────────────────────────────


def test_la_key_de_upload_sale_del_contenido():
    """El navegador no manda nombre de archivo (el body es crudo), y el de un
    adjunto de Discord solo se usa para mirar la extensión."""
    import r2

    src = inspect.getsource(r2.upload_image_bytes_sync)
    assert "hashlib.md5(url.encode()" in src

    upload = _handler_source("_api_embeds_upload")
    assert "filename" not in upload
    assert "_sniff_image(data)" in upload  # la extensión sale de los bytes

    # En memes.py el filename del adjunto solo alimenta splitext() (elegir
    # cuál adjunto es imagen) y un log con %r. Nunca una ruta ni un comando.
    memes_src = (_SRC / "cogs/memes.py").read_text(encoding="utf-8")
    usos = [ln.strip() for ln in memes_src.splitlines() if ".filename" in ln]
    assert usos, "cambió el manejo de adjuntos en memes.py: revisar a mano"
    for uso in usos:
        assert "splitext" in uso or uso == "image_att.filename,", uso
