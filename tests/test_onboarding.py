"""Tests de las funciones puras del onboarding (settings.py).

No arrancan el bot ni tocan la red: los objetos de discord se simulan con
SimpleNamespace (solo se usa .permissions_for y .name).
"""

from types import SimpleNamespace

from cogs.settings import (
    _format_channel_names,
    _scan_channel_visibility,
    _visibility_is_limited,
)


def _channel(name: str, visible: bool):
    perms = SimpleNamespace(view_channel=visible, read_message_history=visible)
    return SimpleNamespace(name=name, permissions_for=lambda me, p=perms: p)


def _guild(channels):
    return SimpleNamespace(me=object(), text_channels=channels)


# ─── _scan_channel_visibility ────────────────────────────────────────────────


def test_scan_separates_visible_and_hidden():
    chans = [_channel("general", True), _channel("staff", False), _channel("bots", True)]
    scan = _scan_channel_visibility(_guild(chans))
    assert scan["total"] == 3
    assert [c.name for c in scan["visible"]] == ["general", "bots"]
    assert [c.name for c in scan["hidden"]] == ["staff"]


def test_scan_needs_both_permissions():
    # view_channel sin read_message_history no alcanza
    perms = SimpleNamespace(view_channel=True, read_message_history=False)
    ch = SimpleNamespace(name="raro", permissions_for=lambda me: perms)
    scan = _scan_channel_visibility(_guild([ch]))
    assert scan["visible"] == [] and len(scan["hidden"]) == 1


# ─── _visibility_is_limited ──────────────────────────────────────────────────


def test_limited_small_server_never_warns():
    scan = {"total": 3, "visible": [], "hidden": [1, 2, 3]}
    assert not _visibility_is_limited(scan)


def test_limited_case_real_3_of_14():
    # El caso que motivó todo: 3 de ~14 canales visibles
    scan = {"total": 14, "visible": [1, 2, 3], "hidden": [0] * 11}
    assert _visibility_is_limited(scan)


def test_limited_couple_staff_channels_is_normal():
    # 8 de 10 visibles: un par de canales privados de staff, no hay que avisar
    scan = {"total": 10, "visible": [0] * 8, "hidden": [0] * 2}
    assert not _visibility_is_limited(scan)


def test_limited_low_ratio_warns():
    scan = {"total": 20, "visible": [0] * 6, "hidden": [0] * 14}
    assert _visibility_is_limited(scan)  # 6/20 = 0.3 < 0.4


# ─── _format_channel_names ───────────────────────────────────────────────────


def test_format_names_short_list():
    chans = [_channel("a", True), _channel("b", True)]
    assert _format_channel_names(chans) == "#a, #b"


def test_format_names_truncates():
    chans = [_channel(f"c{i}", True) for i in range(8)]
    assert _format_channel_names(chans) == "#c0, #c1, #c2, #c3, #c4 (+3)"
