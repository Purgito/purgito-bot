// Calidad: una herramienta de diagnóstico. Separa lo que Purgito debe atender (fallos), lo que depende de
// la configuración de cada servidor (rechazos de Discord, validaciones previas) y lo que tarda (latencia).
import { dataTable, latencyScale, seriesTable, timeChart } from "../charts.mjs";
import { chartOrTable, emptyNote, figure, help, sectionHead, segmented } from "../components.mjs";
import { p95Interval, qualitySignal, rateDelta, SMALL_SAMPLE } from "../derive.mjs";
import { h } from "../dom.mjs";
import { fmtInt, fmtMs, fmtRate, fmtShare } from "../format.mjs";
import { C } from "../palette.mjs";

const ui = { series: "errors", key: "errors", dir: -1 };
const SERIES = {
  errors: { name: "Fallos", color: C.error },
  refused: { name: "Rechazos de Discord", color: C.refused },
  rejected: { name: "Validaciones previas", color: C.rejected },
};

const p95Text = (r) => {
  const iv = p95Interval(r);
  if (!iv) return "—";
  return iv[1] ? `${fmtMs(iv[0])}–${fmtMs(iv[1])}` : "> 30 s";
};

function lanes(data) {
  const s = data.current.summary;
  const attempts = s.successes + s.errors;
  const delivered = attempts + s.refused;
  const partial = data.current.coverage.status !== "complete";
  const iv = p95Interval(s);
  return h("div", { class: "lanes" },
    h("section", { class: "lane lane-errors", "aria-labelledby": "ln-1" },
      h("h2", { class: "lane-title", id: "ln-1" }, "Fiabilidad", help(data.definitions?.errors || "")),
      figure({ label: "Tasa de fallo", value: attempts ? fmtRate(s.error_pct, 2) : "—", size: "lg", delta: rateDelta(s.error_pct, data.previous.summary.error_pct, data.comparison, false), minimum: partial,
        note: attempts ? `${fmtInt(s.errors)} ${s.errors === 1 ? "fallo" : "fallos"} en ${fmtInt(attempts)} intentos` : "Sin intentos en el período" })),
    h("section", { class: "lane lane-ops", "aria-labelledby": "ln-2" },
      h("h2", { class: "lane-title", id: "ln-2" }, "Rechazos operativos", help("Dependen de la configuración de cada servidor o de quien invoca. Se muestran aparte y no entran en la tasa de fallo, pero no se ocultan.")),
      h("div", { class: "lane-pair" },
        figure({ label: "Rechazos de Discord", value: fmtInt(s.refused), note: s.refused ? `${fmtShare(s.refused, delivered)} de los envíos, fuera de la tasa` : "Permisos del bot, canal o mensaje borrado; fuera de la tasa" }),
        figure({ label: "Validaciones previas", value: fmtInt(s.rejected), note: "Permisos de quien invoca, argumentos o cooldown" }))),
    h("section", { class: "lane lane-perf", "aria-labelledby": "ln-3" },
      h("h2", { class: "lane-title", id: "ln-3" }, "Rendimiento", help(data.definitions?.latency || "")),
      h("div", { class: "lane-pair" },
        figure({ label: "Latencia media", value: fmtMs(s.mean_ms), note: s.samples ? `${fmtInt(s.samples)} muestras` : "Sin muestras" }),
        figure({ label: "p95", value: iv ? (iv[1] ? `≤ ${fmtMs(iv[1])}` : "> 30 s") : "—", note: iv && iv[1] ? `Cae entre ${fmtMs(iv[0])} y ${fmtMs(iv[1])}: un tramo del histograma, no un percentil exacto` : "Tramo del histograma, no un percentil exacto" }))));
}

function timeline(data, model, ctx) {
  const unit = model.step === "hour" ? "por hora" : "por día";
  const meta = SERIES[ui.series];
  const values = model[ui.series];
  const any = values.some((v) => v);
  const toggle = segmented("rel-series", Object.entries(SERIES).map(([k, v]) => [k, v.name]), ui.series, (v) => { ui.series = v; ctx.rerender(); }, "Qué mostrar en el tiempo", { small: true });
  const series = [{ key: ui.series, name: meta.name, values, color: meta.color }];
  const body = any
    ? chartOrTable(timeChart({ times: model.times, step: model.step, kind: "columns", series, gaps: model.gaps, window: [model.start, model.end], annotations: model.annotations, label: `${meta.name} ${unit}`, height: 200, unit: "eventos" }), seriesTable(model.times, model.step, series))
    : { button: null, body: emptyNote({ title: model.hasUsage ? `Sin ${meta.name.toLowerCase()} en lo medido` : "Nada que medir todavía", text: model.hasUsage ? "Ninguna ejecución terminó así en este período." : "Aparecerán cuando haya ejecuciones." }) };
  const filtered = ctx.filters.feature ? data.current.features.find((f) => f.feature === ctx.filters.feature)?.label : null;
  return h("section", { class: "rel-time", "aria-labelledby": "rt-t" },
    sectionHead("Cuándo ocurrieron", { id: "rt-t", sub: filtered ? `solo ${filtered}, ${unit}` : `${unit}, UTC`, actions: [toggle, body.button] }),
    body.body);
}

function concentration(data, ctx) {
  const rows = data.current.features.filter((f) => f.uses > 0 && (f.errors || f.refused));
  if (!rows.length) return null;
  const totalErrors = data.current.summary.errors;
  const byErrors = [...rows].sort((a, b) => b.errors - a.errors || b.refused - a.refused).slice(0, 6);
  return h("section", { class: "rel-where", "aria-labelledby": "rw-t" },
    sectionHead("Dónde se concentran", { id: "rw-t", sub: "elige una función para ver cuándo falló" }),
    h("ol", { class: "conc" }, byErrors.map((f) => {
      const attempts = f.successes + f.errors;
      const active = ctx.filters.feature === f.feature;
      return h("li", {},
        h("button", { type: "button", class: "conc-row", "aria-pressed": String(active), onclick: () => ctx.setFilters({ feature: active ? "" : f.feature }) },
          h("span", { class: "conc-name" }, f.label),
          h("span", { class: `conc-err${f.errors ? " has-errors" : ""}` }, f.errors ? `${fmtInt(f.errors)} ${f.errors === 1 ? "fallo" : "fallos"}` : "sin fallos"),
          h("span", { class: "conc-share" }, f.errors && totalErrors && !ctx.filters.feature ? `${fmtShare(f.errors, totalErrors, 0)} del total` : ""),
          h("span", { class: "conc-rate" }, `${fmtRate(f.error_pct, 2)} de ${fmtInt(attempts)}`, f.errors && attempts < SMALL_SAMPLE ? h("small", { class: "small-sample" }, "muestra pequeña") : null),
          h("span", { class: "conc-ref" }, f.refused ? `${fmtInt(f.refused)} ${f.refused === 1 ? "rechazo" : "rechazos"} de Discord` : "")));
    })));
}

function latency(data) {
  const rows = data.current.features.filter((f) => f.samples > 0).sort((a, b) => (b.mean_ms ?? 0) - (a.mean_ms ?? 0));
  if (!rows.length) return h("section", { class: "rel-lat", "aria-labelledby": "rl-t" }, sectionHead("Latencia por función", { id: "rl-t" }), emptyNote({ title: "Sin muestras de latencia", text: "La latencia solo existe donde hay un temporizador instrumentado." }));
  const chart = latencyScale(rows.map((r) => ({ label: r.label, mean: r.mean_ms, interval: p95Interval(r), small: r.samples < SMALL_SAMPLE })), { label: `Latencia media y p95 por función: ${rows.map((r) => `${r.label} ${fmtMs(r.mean_ms)}`).join(", ")}` });
  const table = dataTable(["Función", "Media", "p95 (intervalo)", "Muestras"], rows.map((r) => [r.label, fmtMs(r.mean_ms), p95Text(r), fmtInt(r.samples)]), { caption: "Latencia por función" });
  const { button, body } = chartOrTable(chart, table);
  return h("section", { class: "rel-lat", "aria-labelledby": "rl-t" },
    sectionHead("Latencia por función", { id: "rl-t", sub: "escala logarítmica", actions: [button] }),
    h("p", { class: "lat-key" }, h("span", { class: "lat-key-dot", "aria-hidden": "true" }), "media", h("span", { class: "lat-key-bar", "aria-hidden": "true" }), "intervalo del histograma donde cae el p95"),
    body);
}

function sortable(label, key, rerender) {
  const on = ui.key === key;
  return h("th", { scope: "col", class: key === "label" ? "" : "num", "aria-sort": on ? (ui.dir > 0 ? "ascending" : "descending") : "none" },
    h("button", { type: "button", class: "sort", onclick: () => { ui.dir = on ? -ui.dir : -1; ui.key = key; rerender(); } }, label, h("span", { class: "sort-mark", "aria-hidden": "true" }, on ? (ui.dir > 0 ? "↑" : "↓") : "")));
}

function byFeature(data, rerender) {
  const rows = data.current.features.filter((f) => f.uses > 0).map((f) => ({ ...f, attempts: f.successes + f.errors }));
  if (!rows.length) return null;
  const val = (r) => (ui.key === "label" ? 0 : r[ui.key] ?? -1);
  rows.sort((a, b) => (ui.key === "label" ? a.label.localeCompare(b.label, "es") * ui.dir : (val(a) - val(b)) * ui.dir || b.uses - a.uses));
  return h("section", { class: "rel-table", "aria-labelledby": "rq-t" },
    sectionHead("Calidad por función", { id: "rq-t", sub: `una tasa con fallos y menos de ${SMALL_SAMPLE} intentos se marca como muestra pequeña` }),
    h("div", { class: "table-wrap" }, h("table", { class: "table qtable" }, h("caption", { class: "sr-only" }, "Calidad por función"),
      h("thead", {}, h("tr", {}, sortable("Función", "label", rerender), sortable("Intentos", "attempts", rerender), sortable("Fallos", "errors", rerender), sortable("Tasa de fallo", "error_pct", rerender), sortable("Rechazos Discord", "refused", rerender), sortable("Validaciones", "rejected", rerender), sortable("Media", "mean_ms", rerender), h("th", { scope: "col", class: "num" }, "p95"))),
      h("tbody", {}, rows.map((r) => h("tr", { class: r.errors ? "has-errors" : "" },
        h("th", { scope: "row" }, r.label),
        h("td", { class: "num" }, fmtInt(r.attempts)),
        h("td", { class: "num cell-err" }, fmtInt(r.errors)),
        h("td", { class: "num" }, r.attempts ? fmtRate(r.error_pct, 2) : "—", r.errors && r.attempts < SMALL_SAMPLE ? h("small", { class: "small-sample" }, "muestra pequeña") : null),
        h("td", { class: "num" }, fmtInt(r.refused)),
        h("td", { class: "num" }, fmtInt(r.rejected)),
        h("td", { class: "num" }, fmtMs(r.mean_ms)),
        h("td", { class: "num" }, p95Text(r))))))));
}

export function reliability(ctx) {
  const { data, model } = ctx;
  const root = h("div", { class: "page page-reliability" });
  const q = qualitySignal(data.current.summary);
  root.append(h("p", { class: `rel-lead signal-${q.tone}` }, h("span", { class: "sev", "aria-hidden": "true" }), q.text));
  root.append(lanes(data));
  root.append(h("div", { class: "rel-pair" }, timeline(data, model, ctx), concentration(data, ctx)));
  root.append(latency(data));
  const table = byFeature(data, ctx.rerender);
  if (table) root.append(table);
  return root;
}
