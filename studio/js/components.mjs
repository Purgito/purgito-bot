// Piezas de interfaz compartidas por las siete vistas.
import { h, s, uid } from "./dom.mjs";
import { fmtDuration } from "./format.mjs";
import { COVERAGE_LABEL } from "./derive.mjs";

/* ------------------------------------------------------------------- iconos */

const PATHS = {
  overview: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  growth: "M9 11a3 3 0 100-6 3 3 0 000 6zM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M17 10.5a2.5 2.5 0 100-5M17.5 14.2c2 .5 3.5 2.4 3.5 4.8",
  retention: "M4.5 12a7.5 7.5 0 0112.8-5.3M19.5 12a7.5 7.5 0 01-12.8 5.3M18 3v4h-4M6 21v-4h4",
  features: "M5 20V11M12 20V4M19 20v-6",
  reliability: "M3 12h4l2.5-6 4 12 2.5-6H21",
  versions: "M20.5 12.5l-8 8-9-9V3.5h8z M7.5 8a.5.5 0 100-.01",
  updates: "M5 21V4M5 4h11l-2 4 2 4H5",
  menu: "M4 7h16M4 12h16M4 17h16",
  close: "M6 6l12 12M18 6L6 18",
  check: "M5 12.5l4.5 4.5L19 7.5",
  warn: "M12 4l9 16H3zM12 10v4M12 17.2v.01",
  alert: "M12 3a9 9 0 100 18 9 9 0 000-18zM12 7.5v5.5M12 16.2v.01",
  info: "M12 3a9 9 0 100 18 9 9 0 000-18zM12 11v5.5M12 7.8v.01",
  refresh: "M20 11a8 8 0 00-14.5-3.5M4 4v4h4M4 13a8 8 0 0014.5 3.5M20 20v-4h-4",
  chevron: "M9 6l6 6-6 6",
  lock: "M7 11V8a5 5 0 0110 0v3M5 11h14v9H5z",
};

export function icon(name, { size = 20 } = {}) {
  return s("svg", { class: "icon", width: size, height: size, viewBox: "0 0 24 24", fill: "none", "aria-hidden": "true", focusable: "false" }, s("path", { d: PATHS[name], "stroke-linecap": "round", "stroke-linejoin": "round" }));
}

/* -------------------------------------------------------------- variaciones */

/** Chip de variación: flecha + cifra, tono por dirección (nunca solo color) y aviso de "solo lo observado". */
export function deltaChip(info) {
  if (!info) return null;
  const chip = h("span", { class: `delta delta-${info.kind === "none" ? "none" : info.tone} ${info.kind === "partial" ? "delta-partial" : ""}`, title: info.title }, info.text);
  if (info.spoken) chip.append(h("span", { class: "sr-only" }, `. ${info.spoken}`));
  return chip;
}

/* ----------------------------------------------------------------- métricas */

export function stat({ label, value, note, delta, trend, hero = false, partial = false }) {
  return h("div", { class: `kpi${hero ? " kpi-hero" : ""}` },
    h("div", { class: "kpi-label" }, label, partial ? h("span", { class: "tag", title: "Parte del período no se midió: la cifra es un mínimo." }, "parcial") : null),
    h("div", { class: "kpi-row" }, h("div", { class: "kpi-value" }, value), trend || null),
    delta ? h("div", { class: "kpi-delta" }, deltaChip(delta)) : null,
    note ? h("div", { class: "kpi-note" }, note) : null);
}

/* ------------------------------------------------------------------- panel */

/** Panel con título, leyenda y alternancia gráfico/tabla (todo valor es accesible sin el gráfico). */
export function panel({ title, subtitle, legend, body, table, className = "", headingLevel = 2 }) {
  const id = uid("panel");
  const content = h("div", { class: "panel-body" }, body);
  let tableOn = false;
  const toggle = table
    ? h("button", { type: "button", class: "btn btn-ghost", "aria-pressed": "false", "aria-controls": id, onclick: () => {
        tableOn = !tableOn;
        content.replaceChildren(tableOn ? table : body);
        toggle.setAttribute("aria-pressed", String(tableOn));
        toggle.textContent = tableOn ? "Ver gráfico" : "Ver como tabla";
      } }, "Ver como tabla")
    : null;
  return h("section", { class: `panel ${className}`, "aria-labelledby": `${id}-t` },
    h("header", { class: "panel-head" },
      h("div", {}, h(`h${headingLevel}`, { id: `${id}-t`, class: "panel-title" }, title), subtitle ? h("p", { class: "panel-sub" }, subtitle) : null),
      toggle),
    legend ? h("div", { class: "panel-legend" }, legend) : null,
    h("div", { id }, content));
}

/* ------------------------------------------------------------ estados vacíos */

/** Estado vacío útil: dice qué pasa, por qué y qué se espera (nunca solo "no hay datos"). */
export function emptyState({ title, text, items, compact = false }) {
  return h("div", { class: `empty${compact ? " empty-compact" : ""}` },
    h("p", { class: "empty-title" }, title),
    text ? h("p", { class: "empty-text" }, text) : null,
    items || null);
}

export function milestoneList(items, nowMs) {
  if (!items.length) return null;
  return h("ul", { class: "milestones" }, items.map((m) => h("li", { class: m.done ? "is-done" : "" },
    icon(m.done ? "check" : "chevron", { size: 16 }),
    h("span", { class: "ms-label" }, m.label),
    h("span", { class: "ms-when" }, m.done ? "Disponible" : `en ${fmtDuration(m.remaining / 1000)}`),
    h("span", { class: "ms-note" }, m.note))));
}

/* ----------------------------------------------------------------- cobertura */

const COVERAGE_ICON = { complete: "check", partial: "warn", unavailable: "alert" };

export function coverageChip(status, ratio, { onClick } = {}) {
  const text = `${COVERAGE_LABEL[status]} · ${Math.round(ratio * 1000) / 10}`.replace(".", ",");
  const chip = h(onClick ? "button" : "span", { class: `cov-chip cov-${status}`, type: onClick ? "button" : null, onclick: onClick || null, "aria-haspopup": onClick ? "dialog" : null },
    icon(COVERAGE_ICON[status], { size: 16 }), h("span", {}, `${text} %`));
  return chip;
}

export function badge(text, tone = "neutral", title) {
  return h("span", { class: `badge badge-${tone}`, title: title || null }, text);
}
