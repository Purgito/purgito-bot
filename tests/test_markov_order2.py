"""Tests exhaustivos para SimpleMarkov Orden 2 con Backoff determinista (markov_engine.py)."""

import pytest
from markov_engine import SimpleMarkov


# ─── 1. Construcción y Estados ────────────────────────────────────────────────


def test_empty_and_whitespace_messages_ignored():
    m = SimpleMarkov()
    m.add("")
    m.add("   ")
    m.add([])
    assert m.is_empty
    assert m.generate() is None


def test_add_single_word_creates_correct_transitions():
    m = SimpleMarkov()
    m.add("hola")
    assert not m.is_empty
    # Orden 2
    assert m.transitions_order2[(m.START, m.START)] == ["hola"]
    assert m.transitions_order2[(m.START, "hola")] == [m.END]
    # Orden 1 (Backoff)
    assert m.transitions_order1[m.START] == ["hola"]
    assert m.transitions_order1["hola"] == [m.END]


def test_add_two_words_creates_correct_transitions():
    m = SimpleMarkov()
    m.add("hola mundo")
    # Orden 2
    assert m.transitions_order2[(m.START, m.START)] == ["hola"]
    assert m.transitions_order2[(m.START, "hola")] == ["mundo"]
    assert m.transitions_order2[("hola", "mundo")] == [m.END]
    # Orden 1
    assert m.transitions_order1[m.START] == ["hola"]
    assert m.transitions_order1["hola"] == ["mundo"]
    assert m.transitions_order1["mundo"] == [m.END]


def test_add_multi_word_message():
    m = SimpleMarkov()
    m.add("hola buenas noches a todos")
    assert m.transitions_order2[(m.START, m.START)] == ["hola"]
    assert m.transitions_order2[(m.START, "hola")] == ["buenas"]
    assert m.transitions_order2[("hola", "buenas")] == ["noches"]
    assert m.transitions_order2[("buenas", "noches")] == ["a"]
    assert m.transitions_order2[("noches", "a")] == ["todos"]
    assert m.transitions_order2[("a", "todos")] == [m.END]


def test_add_accepts_pretokenized_list():
    m = SimpleMarkov()
    m.add(["hola", "buenas", "tardes"])
    assert m.transitions_order2[(m.START, "hola")] == ["buenas"]
    assert m.transitions_order2[("buenas", "tardes")] == [m.END]


def test_add_many_aggregates_transitions():
    m = SimpleMarkov()
    m.add_many(["hola buenas", "hola tardes"])
    assert m.transitions_order2[(m.START, m.START)] == ["hola", "hola"]
    assert m.transitions_order2[(m.START, "hola")] == ["buenas", "tardes"]


# ─── 2. START / END y Generación ──────────────────────────────────────────────


def test_generation_starts_from_start_and_stops_at_end():
    m = SimpleMarkov()
    m.add("hola buenas noches")
    res = m.generate()
    assert res == "hola buenas noches"
    assert m.START not in res
    assert m.END not in res


def test_sentinels_never_leak_in_generation():
    m = SimpleMarkov()
    m.add_many([
        "uno dos tres cuatro",
        "cinco seis siete ocho",
    ])
    for _ in range(50):
        res = m.generate()
        assert res is not None
        words = res.split()
        assert m.START not in words
        assert m.END not in words


# ─── 3. Backoff Determinista ──────────────────────────────────────────────────


def test_order2_priority_when_context_exists():
    """Si el estado (s1, s2) existe en orden 2, debe usar la transición de orden 2."""
    m = SimpleMarkov()
    m.add("quiero comer pizza")
    m.add("puedo comer hamburguesa")
    
    assert m.transitions_order2[("quiero", "comer")] == ["pizza"]
    assert m.transitions_order2[("puedo", "comer")] == ["hamburguesa"]


def test_backoff_to_order1_when_order2_context_missing():
    """Si un estado de orden 2 no tiene salida pero la palabra individual sí, hace fallback a orden 1."""
    m = SimpleMarkov()
    m.add("hola mundo")
    m.add("lindo dia")
    
    # Inyectamos una transición forzada en orden 2 que lleve a ('hola', 'lindo')
    # ('hola', 'lindo') no existe en orden 2, pero 'lindo' -> 'dia' existe en orden 1
    m.transitions_order2[(m.START, "hola")].append("lindo")
    
    # ('hola', 'lindo') no está en transitions_order2
    assert ("hola", "lindo") not in m.transitions_order2
    # Pero 'lindo' está en transitions_order1 -> ['dia']
    assert m.transitions_order1["lindo"] == ["dia"]
    
    # Generar debe ser capaz de continuar gracias al backoff
    res = m.generate()
    assert res is not None


def test_backoff_terminates_when_order1_also_empty():
    """Si ni orden 2 ni orden 1 tienen salida, la generación termina limpiamente sin excepción."""
    m = SimpleMarkov()
    m.transitions_order2[(m.START, m.START)] = ["fantasma"]
    res = m.generate(min_words=1)
    assert res == "fantasma"


# ─── 4. Límites y Parámetros ─────────────────────────────────────────────────


def test_max_words_stops_infinite_loops():
    m = SimpleMarkov()
    # Bucle infinito: a b a b a b ...
    m.transitions_order2[(m.START, m.START)] = ["a"]
    m.transitions_order2[(m.START, "a")] = ["b"]
    m.transitions_order2[("a", "b")] = ["a"]
    m.transitions_order2[("b", "a")] = ["b"]
    
    res = m.generate(max_words=10)
    assert res is not None
    assert len(res.split()) == 10


def test_min_words_retries_and_returns_none_if_impossible():
    m = SimpleMarkov()
    m.add("hola")  # Genera solo 1 palabra
    res = m.generate(min_words=5, max_attempts=3)
    assert res is None


def test_single_word_generation_works_with_min_words_1():
    m = SimpleMarkov()
    m.add("hola")
    res = m.generate(min_words=1)
    assert res == "hola"


# ─── 5. Tokenización (generation.tokenize_message) ───────────────────────────


def test_tokenize_strips_punctuation_from_words():
    from generation import tokenize_message
    assert tokenize_message("sting,") == ["sting"]
    assert tokenize_message("emi,") == ["emi"]
    assert tokenize_message("hola!") == ["hola"]
    assert tokenize_message("¿qué?") == ["qué"]
    assert tokenize_message("¡buenas!") == ["buenas"]


def test_tokenize_discards_floating_dots_and_commas():
    from generation import tokenize_message
    assert tokenize_message("no sale . dolares") == ["no", "sale", "dolares"]
    assert tokenize_message("... ...") == []
    assert tokenize_message("hola , mundo") == ["hola", "mundo"]


def test_tokenize_preserves_slang_and_accents():
    from generation import tokenize_message
    assert tokenize_message("xd lol 100k") == ["xd", "lol", "100k"]
    assert tokenize_message("más está canción contraseña") == ["más", "está", "canción", "contraseña"]


def test_tokenize_strips_markdown():
    from generation import tokenize_message
    assert tokenize_message("**negrita** ||spoiler|| `codigo`") == ["negrita", "spoiler", "codigo"]
