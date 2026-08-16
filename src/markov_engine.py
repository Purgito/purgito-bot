import random
from collections import defaultdict


class SimpleMarkov:
    """Generador de cadenas de Markov de segundo orden con backoff determinista a primer orden.

    Características clave:
    - Estado principal: tupla de 2 palabras (w_{t-2}, w_{t-1}).
    - Backoff a primer orden (w_{t-1}) cuando el estado de segundo orden no tiene transiciones.
    - Termina naturalmente cuando la cadena alcanza fin-de-mensaje (__END__).
    - Las transiciones se pesan por frecuencia natural empírica (lista con repetición).
    """

    START = "__START__"
    END = "__END__"

    def __init__(self):
        self.transitions_order2: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.transitions_order1: dict[str, list[str]] = defaultdict(list)

    def add(self, message: str | list[str]) -> None:
        if isinstance(message, list):
            words = [str(w).lower() for w in message if str(w).strip()]
        else:
            words = (message or "").lower().split()
        if not words:
            return

        # 1. Poblar transiciones de Orden 2
        state = (self.START, self.START)
        for word in words:
            self.transitions_order2[state].append(word)
            state = (state[1], word)
        self.transitions_order2[state].append(self.END)

        # 2. Poblar transiciones de Orden 1 (tabla de backoff)
        prev = self.START
        for word in words:
            self.transitions_order1[prev].append(word)
            prev = word
        self.transitions_order1[prev].append(self.END)

    def add_many(self, messages: list[str | list[str]]) -> None:
        for msg in messages:
            self.add(msg)

    def generate(
        self,
        max_words: int = 20,
        max_attempts: int = 5,
        min_words: int = 1,
    ) -> str | None:
        if not self.transitions_order2:
            return None

        for _ in range(max_attempts):
            state = (self.START, self.START)
            words: list[str] = []

            for _ in range(max_words):
                # 1. Consultar orden 2
                options = self.transitions_order2.get(state)

                # 2. Backoff a orden 1 si el estado de orden 2 no tiene transiciones
                if not options:
                    options = self.transitions_order1.get(state[1])

                if not options:
                    break

                next_word = random.choice(options)
                if next_word == self.END:
                    break

                words.append(next_word)
                state = (state[1], next_word)

            if len(words) >= min_words:
                return " ".join(words)

        return None

    @property
    def is_empty(self) -> bool:
        return not self.transitions_order2
