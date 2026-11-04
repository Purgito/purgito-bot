// Piezas de interfaz compartidas. Fundamentos comunes (iconos, cifras, ayuda, conmutadores); la
// composición de cada página la decide su vista.
import { h, s, uid } from "./dom.mjs";
import { fmtDuration } from "./format.mjs";

/* ------------------------------------------------------------------- iconos */

const PATHS = {
  overview: "M4 13h4v7H4zM10 4h4v16h-4zM16 9h4v11h-4z",
  growth: "M9 11a3 3 0 100-6 3 3 0 000 6zM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M17 10.5a2.5 2.5 0 100-5M17.5 14.2c2 .5 3.5 2.4 3.5 4.8",
  retention: "M4 5h4v4H4zM10 5h4v4h-4zM16 5h4v4h-4zM4 11h4v4H4zM10 11h4v4h-4zM4 17h4v3H4z",
  features: "M4 6h10M4 12h16M4 18h6",
  reliability: "M3 12h4l2.5-6 4 12 2.5-6H21",
  versions: "M6 3v18M6 8c6 0 6 4 12 4M18 12v9",
  updates: "M12 4v16M6 8h6M12 14h6M6 8a1.5 1.5 0 11-.01 0M18 14a1.5 1.5 0 11-.01 0",
  menu: "M4 7h16M4 12h16M4 17h16",
  close: "M6 6l12 12M18 6L6 18",
  check: "M5 12.5l4.5 4.5L19 7.5",
  info: "M12 3a9 9 0 100 18 9 9 0 000-18zM12 11v5.5M12 7.8v.01",
  refresh: "M20 11a8 8 0 00-14.5-3.5M4 4v4h4M4 13a8 8 0 0014.5 3.5M20 20v-4h-4",
  chevron: "M9 6l6 6-6 6",
  down: "M6 9l6 6 6-6",
  filter: "M4 6h16M7 12h10M10 18h4",
  plus: "M12 5v14M5 12h14",
  search: "M11 4a7 7 0 100 14 7 7 0 000-14zM20 20l-4-4",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  book: "M5 4h10a3 3 0 013 3v13H8a3 3 0 01-3-3zM5 17a3 3 0 013-3h10",
};

export function icon(name, { size = 18 } = {}) {
  return s("svg", { class: "icon", width: size, height: size, viewBox: "0 0 24 24", fill: "none", "aria-hidden": "true", focusable: "false" }, s("path", { d: PATHS[name], "stroke-linecap": "round", "stroke-linejoin": "round" }));
}

/* -------------------------------------------------------------- variaciones */

/** Variación: flecha + cifra, tono por dirección (nunca solo color) y aviso de "solo lo observado". */
export function deltaChip(info) {
  // "Sin comparación" ya lo dice la cabecera del período: repetirlo en cada cifra solo añade ruido.
  if (!info || info.kind === "none") return null;
  const tone = info.kind === "none" ? "none" : info.tone;
  const chip = h("span", { class: `delta delta-${tone}${info.kind === "partial" ? " delta-partial" : ""}`, title: info.title || null }, info.text);
  if (info.spoken) chip.append(h("span", { class: "sr-only" }, `. ${info.spoken}`));
  return chip;
}

/* ----------------------------------------------------------- ayuda contextual */

/**
 * Ayuda bajo demanda (toggletip): un botón ⓘ que abre una nota corta. Escape o un clic fuera la cierran.
 * El texto vive en el DOM (accesible), no en un atributo title.
 */
export function help(text, { label = "Qué significa" } = {}) {
  const id = uid("help");
  const bubble = h("span", { class: "help-bubble", id, role: "note", hidden: true }, text);
  const button = h("button", { type: "button", class: "help", "aria-expanded": "false", "aria-controls": id, "aria-label": label }, icon("info", { size: 15 }));
  button.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = button.getAttribute("aria-expanded") !== "true";
    closeHelps();
    if (open) {
      bubble.hidden = false;
      button.setAttribute("aria-expanded", "true");
    }
  });
  return h("span", { class: "help-wrap" }, button, bubble);
}

export function closeHelps() {
  for (const b of document.querySelectorAll('.help[aria-expanded="true"]')) {
    b.setAttribute("aria-expanded", "false");
    document.getElementById(b.getAttribute("aria-controls")).hidden = true;
  }
}
if (typeof document !== "undefined") {
  document.addEventListener("click", (e) => !e.target.closest?.(".help-bubble") && closeHelps());
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeHelps());
}

/* ------------------------------------------------------------------ cifras */

/**
 * Una cifra con su etiqueta, sin caja. `minimum`: parte del período no se midió y la cifra es un
 * mínimo (se dice en texto, no solo con color).
 */
export function figure({ label, value, unit, note, delta, info, minimum = false, size = "md", className = "" }) {
  const chip = deltaChip(delta);
  return h("div", { class: `fig fig-${size} ${className}` },
    h("div", { class: "fig-label" }, label, info ? help(info, { label: `Qué significa: ${label}` }) : null),
    h("div", { class: "fig-value" }, value, unit ? h("span", { class: "fig-unit" }, unit) : null),
    chip || minimum ? h("div", { class: "fig-meta" }, chip, minimum ? h("span", { class: "minimum", title: "Parte del período no se midió: la cifra es un mínimo." }, "mínimo") : null) : null,
    note ? h("div", { class: "fig-note" }, note) : null);
}

/* ----------------------------------------------------------------- secciones */

/** Encabezado de sección: título, ayuda opcional y acciones a la derecha. Sin caja alrededor. */
export function sectionHead(title, { info, actions, sub, level = 2, id } = {}) {
  return h("header", { class: "sec-head" },
    h("div", { class: "sec-title-row" }, h(`h${level}`, { class: "sec-title", id: id || null }, title), info ? help(info, { label: `Qué significa: ${title}` }) : null, sub ? h("span", { class: "sec-sub" }, sub) : null),
    actions ? h("div", { class: "sec-actions" }, actions) : null);
}

/**
 * Alterna entre una visualización y su tabla equivalente (todo valor es accesible sin el gráfico).
 * Devuelve { button, body }.
 */
export function chartOrTable(chart, table) {
  const id = uid("view");
  const body = h("div", { id, class: "view-body" }, chart);
  if (!table) return { button: null, body };
  let on = false;
  const button = h("button", { type: "button", class: "btn btn-quiet", "aria-pressed": "false", "aria-controls": id }, "Ver como tabla");
  button.addEventListener("click", () => {
    on = !on;
    body.replaceChildren(on ? table : chart);
    button.setAttribute("aria-pressed", String(on));
    button.textContent = on ? "Ver gráfico" : "Ver como tabla";
  });
  return { button, body };
}

/** Control segmentado accesible (radios). options: [[value, text]]. */
export function segmented(name, options, current, onChange, legend, { small = false } = {}) {
  return h("fieldset", { class: `seg${small ? " seg-sm" : ""}` }, h("legend", { class: "sr-only" }, legend),
    options.map(([value, text]) => h("label", {}, h("input", { type: "radio", name, value, checked: value === current ? true : null, onchange: () => onChange(value) }), h("span", {}, text))));
}

/* ------------------------------------------------------------ estados vacíos */

/** Estado vacío integrado: qué pasa y qué se espera. `action` es un botón real o nada. */
export function emptyNote({ title, text, action, items, tone = "quiet" }) {
  return h("div", { class: `empty empty-${tone}` },
    h("p", { class: "empty-title" }, title),
    text ? h("p", { class: "empty-text" }, text) : null,
    items || null,
    action || null);
}

/** Próximos hitos de datos como una pista temporal compacta. */
export function milestoneTrack(items, startMs, nowMs) {
  if (!items.length) return null;
  const last = Math.max(...items.map((i) => i.at), nowMs + 1);
  const span = last - startMs;
  const pct = (t) => `${Math.max(0, Math.min(100, (100 * (t - startMs)) / span))}%`;
  const rail = h("div", { class: "ms-rail", "aria-hidden": "true" }, h("span", { class: "ms-done" }));
  rail.firstChild.style.setProperty("--w", pct(nowMs));
  const now = h("span", { class: "ms-now" }, "hoy");
  now.style.setProperty("--l", pct(nowMs));
  rail.append(now);
  for (const m of items) {
    const dot = h("span", { class: `ms-dot${m.done ? " is-done" : ""}` });
    dot.style.setProperty("--l", pct(m.at));
    rail.append(dot);
  }
  return h("div", { class: "milestones" }, rail,
    h("ol", { class: "ms-list" }, items.map((m) => h("li", { class: m.done ? "is-done" : "" },
      h("span", { class: "ms-label" }, m.label),
      h("span", { class: "ms-when" }, m.done ? "Disponible" : `en ${fmtDuration(m.remaining / 1000)}`),
      m.note ? h("span", { class: "ms-note" }, m.note) : null))));
}

export function badge(text, tone = "neutral", title) {
  return h("span", { class: `badge badge-${tone}`, title: title || null }, text);
}

/** Enlace a otra vista dentro de Studio (botón con aspecto de enlace; conserva filtros). */
export function goTo(text, onClick) {
  return h("button", { type: "button", class: "link", onclick: onClick }, text);
}
