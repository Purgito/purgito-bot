// Funciones: dónde se concentra el uso, cuánto alcance tiene cada función, cómo de fiable es y qué
// comandos la componen. Lo instrumentado sin uso y lo no instrumentado se muestran aparte: no medir no
// es lo mismo que cero.
import { shareStrip, swatch } from "../charts.mjs";
import { deltaChip, emptyNote, help, icon, sectionHead, segmented } from "../components.mjs";
import { commandFeature, featureGroups, p95Interval, SMALL_SAMPLE } from "../derive.mjs";
import { h } from "../dom.mjs";
import { fmtInt, fmtMs, fmtNum, fmtRate, fmtShare } from "../format.mjs";
import { categorical, OTHER } from "../palette.mjs";

const COVERAGE = {
  commands_and_deliveries: ["Comandos y entregas", "Se miden los comandos registrados y las entregas automáticas."],
  deliveries: ["Entregas", "Solo se miden las entregas: no hay comandos registrados."],
  commands: ["Comandos", "Se miden los comandos registrados."],
  explicit_events: ["Eventos explícitos", "Sin comandos ni entregas: solo cuenta lo que se registre a mano."],
  not_instrumented: ["Sin instrumentar", "No hay adaptador ni comandos: no se mide, y eso no es lo mismo que cero uso."],
};
const SOURCE = { prefix: "Prefijo", slash: "Slash", mention: "Mención", trigger: "Trigger", spontaneous: "Espontáneo", background: "Aviso", delivery: "Entrega" };

const ui = { key: "uses", dir: -1, open: null, cmdFilter: "", cmdSource: "", cmdSort: "uses", cmdLimit: 12 };

/** Abre el detalle de una función al llegar desde otra página. */
export function focusFeature(id) {
  ui.open = id;
}

function sortable(label, key, rerender, numeric = true) {
  const on = ui.key === key;
  return h("th", { scope: "col", class: numeric ? "num" : "", "aria-sort": on ? (ui.dir > 0 ? "ascending" : "descending") : "none" },
    h("button", { type: "button", class: "sort", onclick: () => { ui.dir = on ? -ui.dir : -1; ui.key = key; rerender(); } }, label, h("span", { class: "sort-mark", "aria-hidden": "true" }, on ? (ui.dir > 0 ? "↑" : "↓") : "")));
}

function bar(value, max, cls = "") {
  const track = h("span", { class: `cell-bar ${cls}`, "aria-hidden": "true" }, h("span", {}));
  track.firstChild.style.setProperty("--w", `${max ? Math.max(value > 0 ? 1.2 : 0, (100 * value) / max) : 0}%`);
  return track;
}

function failCell(r) {
  const attempts = (r.successes || 0) + (r.errors || 0);
  if (!attempts) return h("span", { class: "muted" }, "—");
  return h("span", { class: `rate${r.errors ? " has-errors" : ""}` }, fmtRate(r.error_pct, 2),
    h("small", {}, `${fmtInt(r.errors)} de ${fmtInt(attempts)}`),
    r.errors && attempts < SMALL_SAMPLE ? h("small", { class: "small-sample", title: `Menos de ${SMALL_SAMPLE} intentos: la tasa es poco fiable.` }, "muestra pequeña") : null);
}

function detail(r, cmds, ctx) {
  const interval = p95Interval(r);
  return h("div", { class: "fdetail" },
    h("dl", { class: "facts facts-compact" },
      h("div", {}, h("dt", {}, "Correctas"), h("dd", {}, fmtInt(r.successes))),
      h("div", {}, h("dt", {}, "Rechazos de Discord"), h("dd", {}, fmtInt(r.refused))),
      h("div", {}, h("dt", {}, "Validaciones previas"), h("dd", {}, fmtInt(r.rejected))),
      h("div", {}, h("dt", {}, "Latencia media"), h("dd", {}, fmtMs(r.mean_ms))),
      h("div", {}, h("dt", {}, "p95"), h("dd", {}, interval ? (interval[1] ? `entre ${fmtMs(interval[0])} y ${fmtMs(interval[1])}` : "más de 30 s") : "—")),
      h("div", {}, h("dt", {}, "Muestras de latencia"), h("dd", {}, fmtInt(r.samples)))),
    cmds.length ? h("div", { class: "fdetail-cmds" }, h("p", { class: "fdetail-label" }, "Comandos de esta función"),
      h("ul", { class: "cmd-mini" }, cmds.slice(0, 8).map((c) => h("li", {}, h("code", {}, c.command), h("span", { class: "muted" }, SOURCE[c.source] || c.source), h("span", { class: "num" }, fmtInt(c.uses)))))) : h("p", { class: "fdetail-label" }, r.coverage === "deliveries" ? "Solo entregas automáticas: no tiene comandos registrados." : "Sin comandos registrados en el período."),
    h("div", { class: "fdetail-actions" },
      h("button", { type: "button", class: "btn btn-quiet", onclick: () => ctx.nav("overview", { feature: r.feature }) }, "Ver su actividad en el tiempo"),
      h("button", { type: "button", class: "btn btn-quiet", onclick: () => ctx.nav("reliability", { feature: r.feature }) }, "Ver su calidad")));
}

function featureTable(used, total, ctx, cmdsOf) {
  const { rerender } = ctx;
  const color = categorical(used.map((f) => f.feature).slice(0, 6));
  const rows = [...used];
  const val = (r) => (ui.key === "share" ? r.uses : r[ui.key] ?? -1);
  rows.sort((a, b) => (ui.key === "label" ? a.label.localeCompare(b.label, "es") * ui.dir : (val(a) - val(b)) * ui.dir));
  const maxUses = Math.max(...used.map((r) => r.uses));
  const body = [];
  for (const r of rows) {
    const [cov, why] = COVERAGE[r.coverage] || ["—", ""];
    const open = ui.open === r.feature;
    const id = `fd-${r.feature}`;
    const change = r.adoption_change_pp;
    body.push(h("tr", { class: open ? "is-open" : "" },
      h("th", { scope: "row" },
        h("button", { type: "button", class: "row-toggle", "aria-expanded": String(open), "aria-controls": id, onclick: () => { ui.open = open ? null : r.feature; rerender(); } },
          icon("chevron", { size: 14 }), swatch(color(r.feature), "box"), h("span", { class: "fname" }, r.label)),
        h("span", { class: "fcov", title: why }, cov)),
      h("td", { class: "num cell-uses" }, bar(r.uses, maxUses), h("span", { class: "cell-num" }, fmtInt(r.uses))),
      h("td", { class: "num" }, fmtShare(r.uses, total)),
      h("td", { class: "num cell-reach" }, r.adoption_pct == null ? fmtInt(r.served) : [bar(r.adoption_pct, 100, "bar-reach"), h("span", { class: "cell-num" }, fmtInt(r.served), h("small", {}, fmtRate(r.adoption_pct, 1)))]),
      h("td", { class: "num" }, change == null ? h("span", { class: "muted" }, "—") : deltaChip({ kind: "full", tone: "neutral", text: Math.abs(change) < 0.05 ? "= sin cambio" : `${change > 0 ? "▲" : "▼"} ${fmtNum(Math.abs(change), 1)} pp`, title: "Puntos porcentuales de adopción frente al período anterior", spoken: Math.abs(change) < 0.05 ? "Sin cambio de adopción" : `${change > 0 ? "Sube" : "Baja"} ${fmtNum(Math.abs(change), 1)} puntos de adopción` })),
      h("td", { class: "num" }, failCell(r))));
    if (open) body.push(h("tr", { class: "detail-row", id }, h("td", { colspan: 6 }, detail(r, cmdsOf(r.feature), ctx))));
  }
  return h("div", { class: "table-wrap" }, h("table", { class: "table ftable" }, h("caption", { class: "sr-only" }, "Funciones usadas: volumen, alcance, cambio y fiabilidad"),
    h("thead", {}, h("tr", {}, sortable("Función", "label", rerender, false), sortable("Usos", "uses", rerender), sortable("Cuota", "share", rerender), sortable("Comunidades", "served", rerender), sortable("Cambio de adopción", "adoption_change_pp", rerender), sortable("Tasa de fallo", "error_pct", rerender))),
    h("tbody", {}, body)));
}

function commandExplorer(data, ctx, featureOf) {
  const all = data.current.commands;
  const labels = Object.fromEntries(data.current.features.map((f) => [f.feature, f.label]));
  if (!all.length) return emptyNote({ title: "Sin comandos ejecutados", text: "Aparecerán cuando alguien use un comando registrado." });
  const sources = [...new Set(all.map((c) => c.source))];
  const q = ui.cmdFilter.toLowerCase();
  let list = all.filter((c) => c.command.toLowerCase().includes(q) && (!ui.cmdSource || c.source === ui.cmdSource));
  const sortKey = { uses: (c) => c.uses, errors: (c) => c.errors, error_pct: (c) => c.error_pct ?? -1, served: (c) => c.served }[ui.cmdSort];
  list = [...list].sort((a, b) => sortKey(b) - sortKey(a) || b.uses - a.uses);
  const shown = list.slice(0, ui.cmdLimit);
  const max = Math.max(1, ...all.map((c) => c.uses));
  const search = h("label", { class: "search" }, icon("search", { size: 16 }), h("input", { type: "search", class: "input", id: "cmd-filter", placeholder: "Buscar comando", "aria-label": "Buscar comando", value: ui.cmdFilter, autocomplete: "off", oninput: (e) => { ui.cmdFilter = e.target.value; ui.cmdLimit = 12; ctx.rerender({ keepFocus: "cmd-filter" }); } }));
  const order = h("label", { class: "field field-inline" }, h("span", { class: "field-label" }, "Ordenar por"),
    h("select", { class: "input", onchange: (e) => { ui.cmdSort = e.target.value; ctx.rerender(); } }, [["uses", "Intentos"], ["served", "Comunidades"], ["errors", "Fallos"], ["error_pct", "Tasa de fallo"]].map(([v, t]) => h("option", { value: v, selected: v === ui.cmdSort ? true : null }, t))));
  const sourceSeg = sources.length > 1 ? segmented("cmd-source", [["", "Todas"], ...sources.map((s) => [s, SOURCE[s] || s])], ui.cmdSource, (v) => { ui.cmdSource = v; ui.cmdLimit = 12; ctx.rerender(); }, "Tipo de entrada", { small: true }) : null;
  return h("div", { class: "cmds" },
    h("div", { class: "cmds-tools" }, search, sourceSeg, order),
    shown.length ? h("div", { class: "table-wrap" }, h("table", { class: "table ctable" }, h("caption", { class: "sr-only" }, "Uso por comando"),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Comando"), h("th", { scope: "col" }, "Función"), h("th", { scope: "col", class: "num" }, "Intentos"), h("th", { scope: "col", class: "num" }, "Comunidades"), h("th", { scope: "col", class: "num" }, "Tasa de fallo"))),
      h("tbody", {}, shown.map((c) => h("tr", {},
        h("th", { scope: "row" }, h("code", { class: "cmd" }, c.command), h("span", { class: "src" }, SOURCE[c.source] || c.source)),
        h("td", {}, labels[featureOf(c)] || h("span", { class: "muted" }, "—")),
        h("td", { class: "num cell-uses" }, bar(c.uses, max), h("span", { class: "cell-num" }, fmtInt(c.uses))),
        h("td", { class: "num" }, fmtInt(c.served)),
        h("td", { class: "num" }, failCell(c))))))) : h("p", { class: "empty-text" }, "Ningún comando coincide con la búsqueda."),
    shown.length < list.length ? h("button", { type: "button", class: "btn btn-quiet more", onclick: () => { ui.cmdLimit += 24; ctx.rerender(); } }, `Mostrar ${fmtInt(Math.min(24, list.length - shown.length))} más de ${fmtInt(list.length - shown.length)}`) : null);
}

export function features(ctx) {
  const { data, model } = ctx;
  const cur = data.current;
  const root = h("div", { class: "page page-features" });
  const { used, idle, blind, total } = featureGroups(cur.features);
  const featureOf = commandFeature(data.catalog);
  const cmdsOf = (f) => cur.commands.filter((c) => featureOf(c) === f).sort((a, b) => b.uses - a.uses);
  const partial = cur.coverage.status !== "complete";

  if (!used.length) {
    root.append(emptyNote({ title: "Todavía no hay uso de funciones", text: model.measuring ? "Cuando haya ejecuciones o entregas aparecerán aquí, ordenadas por volumen." : "Studio todavía no ha medido nada." }));
  } else {
    const color = categorical(used.map((f) => f.feature).slice(0, 6));
    const top2 = used.slice(0, 2);
    const conc = top2.length > 1 ? `${top2[0].label} y ${top2[1].label} reúnen el ${fmtShare(top2[0].uses + top2[1].uses, total, 0)} de ${fmtInt(total)} usos` : `${top2[0].label}: ${fmtInt(total)} usos`;
    root.append(h("section", { class: "fshare", "aria-labelledby": "fs-t" },
      sectionHead("Reparto del uso", { id: "fs-t", sub: conc, info: data.definitions?.scope }),
      shareStrip(used.map((f) => ({ key: f.feature, label: f.label, value: f.uses, color: color(f.feature) })), { ariaLabel: `Reparto del uso: ${used.map((f) => `${f.label} ${fmtShare(f.uses, total)}`).join(", ")}` }),
      h("p", { class: "fshare-keys" }, used.slice(0, 6).map((f) => h("span", {}, swatch(color(f.feature), "box"), f.label)), used.length > 6 ? h("span", {}, swatch(OTHER, "box"), `otras ${used.length - 6}`) : null)));

    root.append(h("section", { class: "fmain", "aria-labelledby": "fm-t" },
      sectionHead("Funciones usadas", { id: "fm-t", sub: partial ? "lo observado es un mínimo: parte del período sin medir" : null, info: data.definitions?.adoption }),
      featureTable(used, total, ctx, cmdsOf)));
  }

  if (idle.length || blind.length)
    root.append(h("section", { class: "fquiet", "aria-labelledby": "fq-t" },
      h("h2", { class: "sr-only", id: "fq-t" }, "Funciones sin uso observado o sin instrumentar"),
      idle.length ? h("div", { class: "fquiet-group" },
        h("h3", { class: "fquiet-title" }, "Sin uso observado", help("Se miden, pero no registraron ninguna ejecución ni entrega en el período." + (partial ? " Con la cobertura incompleta, «0 observados» no garantiza cero uso." : ""))),
        h("ul", { class: "pills" }, idle.map((f) => h("li", {}, f.label, h("small", {}, COVERAGE[f.coverage]?.[0] || ""))))) : null,
      blind.length ? h("div", { class: "fquiet-group" },
        h("h3", { class: "fquiet-title" }, "Sin instrumentar", help(COVERAGE.not_instrumented[1])),
        h("ul", { class: "pills pills-blind" }, blind.map((f) => h("li", {}, f.label)))) : null));

  root.append(h("section", { class: "fcmds", "aria-labelledby": "fc-t" },
    sectionHead("Comandos", { id: "fc-t", sub: "solo comandos registrados, nunca sus argumentos" }),
    commandExplorer(data, ctx, featureOf)));
  return root;
}

