// Colores de datos (definidos en studio.css). Semánticos: significan un resultado y nunca se usan para
// distinguir categorías. Categóricos: distinguen funciones o versiones y nunca significan nada bueno o malo.
export const C = {
  current: "var(--c-current)",
  prev: "var(--c-prev)",
  ok: "var(--c-ok)",
  error: "var(--c-error)",
  refused: "var(--c-refused)",
  rejected: "var(--c-rejected)",
  entries: "var(--c-current)",
  rejoins: "var(--c-rejoin)",
  exits: "var(--c-exit)",
};

export const CATEGORICAL = ["var(--cat-1)", "var(--cat-2)", "var(--cat-3)", "var(--cat-4)", "var(--cat-5)", "var(--cat-6)"];
export const OTHER = "var(--cat-other)";

/** Color estable por clave dentro de una lista ordenada (las primeras, en color; el resto, "otras"). */
export function categorical(keys, limit = CATEGORICAL.length) {
  const map = new Map(keys.slice(0, limit).map((k, i) => [k, CATEGORICAL[i]]));
  return (key) => map.get(key) || OTHER;
}
