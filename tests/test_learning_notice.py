"""Aviso y confirmación del administrador al activar el aprendizaje de un canal (Discord)."""

import asyncio
from types import SimpleNamespace

import pytest

import db
import learning_notice as ln


@pytest.fixture
def mem():
    asyncio.run(db.init_db())

    async def _clean():
        conn = await db.get_db()
        async with db._db_lock:
            for t in ("corpus_allowed_channels", "audit_log"):
                await conn.execute(f"DELETE FROM {t} WHERE guild_id = 777")
            await conn.commit()

    asyncio.run(_clean())
    yield
    asyncio.run(_clean())
    asyncio.run(db.close_db())


class _Host:
    def __init__(self):
        self.guild = SimpleNamespace(id=777)
        self.locale = "es"
        self.invoker_id = 42
        self.refreshed = 0

    async def refresh(self, interaction):
        self.refreshed += 1


def _interaction():
    sent = {}

    async def edit_message(**kw):
        sent.update(kw)

    return SimpleNamespace(
        user=SimpleNamespace(id=42, display_name="admin"),
        response=SimpleNamespace(edit_message=edit_message),
    ), sent


def test_el_aviso_dice_lo_que_debe_decir_en_los_dos_idiomas():
    for loc, words in (
        ("es", ("Markov", "30 días", "privacidad", "informar")),
        ("en", ("Markov", "30 days", "privacidad", "tell")),
    ):
        text = ln.build_notice_embed(loc, [5, 6]).description
        assert "<#5>" in text and "<#6>" in text
        for w in words:
            assert w in text, (loc, w)
        assert "https://purgito.app/privacidad" in text
    # los enlaces a los Términos y a la Política van en el idioma de quien administra
    assert ln.terms_url("en").endswith("/en/terms") and ln.privacy_url("es").endswith(
        "/es/privacidad"
    )


def test_pedir_la_activacion_muestra_el_aviso_y_no_guarda_nada(mem):
    host, (inter, sent) = _Host(), _interaction()
    asyncio.run(ln.request_learning_activation(inter, host, [10, 11], "settings"))
    assert sent["embed"].title and isinstance(sent["view"], ln.LearningConfirmView)
    assert (
        asyncio.run(db.list_corpus_channels(777)) == []
    )  # explícito: nada se activa sin confirmar
    links = [i.url for i in sent["view"].children if getattr(i, "url", None)]
    assert any(u.endswith("/es/terminos") for u in links) and any(
        u.endswith("/es/privacidad") for u in links
    )


def test_confirmar_activa_los_canales_y_deja_la_auditoria_minima(mem):
    host, (inter, _sent) = _Host(), _interaction()
    view = ln.LearningConfirmView(host, [10, 11], "settings")
    asyncio.run(view._on_confirm(inter))
    assert sorted(asyncio.run(db.list_corpus_channels(777))) == [10, 11]
    assert host.refreshed == 1
    entries = asyncio.run(db.list_audit_log(777))
    assert len(entries) == 2 and {e["action"] for e in entries} == {"corpus.add"}
    for e in entries:
        assert e["user_id"] == 42
        assert (
            f"notice={ln.NOTICE_VERSION}" in e["detail"]
            and "source=settings" in e["detail"]
        )
        assert "content" not in e["detail"]


def test_cancelar_no_activa_nada_ni_registra(mem):
    host, (inter, _sent) = _Host(), _interaction()
    view = ln.LearningConfirmView(host, [10], "setup")
    asyncio.run(view._on_cancel(inter))
    assert asyncio.run(db.list_corpus_channels(777)) == []
    assert asyncio.run(db.list_audit_log(777)) == []
    assert host.refreshed == 1


def test_confirmar_dos_veces_no_duplica_ni_pierde_la_configuracion_existente(mem):
    asyncio.run(db.add_corpus_channel(777, 9))  # canal ya habilitado antes: no se toca
    host, (inter, _sent) = _Host(), _interaction()
    view = ln.LearningConfirmView(host, [9, 10], "settings")
    asyncio.run(view._on_confirm(inter))
    asyncio.run(view._on_confirm(inter))
    assert sorted(asyncio.run(db.list_corpus_channels(777))) == [9, 10]
    assert (
        len(asyncio.run(db.list_audit_log(777))) == 1
    )  # solo el canal realmente nuevo
