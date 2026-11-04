// Calidad: qué falla de verdad, qué rechaza Discord por configuración y cuánto tarda.
import { dataTable, legend, segmentedBar, timeChart } from "../charts.mjs";
import { emptyState, panel, stat } from "../components.mjs";
import { rateDelta } from "../derive.mjs";
import { h } from "../dom.mjs";
import { fmtInt, fmtMs, fmtPct } from "../format.mjs";
import { COLORS } from "./overview.mjs";

export function reliability({ data, model }) {
  const cur = data.current;
  const s = cur.summary;
  const attempts = s.successes + s.errors;
  const root = h("div", { class: "stack" });
  const partial = cur.coverage.status !== "complete";

  root.append(
    h("div", { class: "kpis kpis-5" },
      stat({ label: "Tasa de fallo", value: fmtPct(s.error_pct), delta: rateDelta(s.error_pct, data.previous.summary.error_pct, data.comparison, false), note: attempts ? `${fmtInt(s.errors)} fallos ÷ ${fmtInt(attempts)} intentos` : "Sin intentos", partial }),
      stat({ label: "Rechazos de Discord", value: fmtInt(s.refused), note: s.refused ? `${fmtPct(s.refused_pct)} de los intentos · fuera de la tasa` : "Permisos del bot, canal o mensaje borrado", partial }),
      stat({ label: "Validaciones previas", value: fmtInt(s.rejected), note: "Permisos de quien invoca, argumentos o cooldown", partial }),
      stat({ label: "Latencia media", value: fmtMs(s.mean_ms), note: s.samples ? `${fmtInt(s.samples)} muestras` : "Sin muestras" }),
      stat({ label: "Latencia p95", value: s.p95_ms_upper_bound ? `≤ ${fmtMs(s.p95_ms_upper_bound)}` : s.p95_over_30000_ms ? "> 30 s" : "—", note: "Límite superior del tramo del histograma" }),
    ),
    h("p", { class: "note" }, "Un fallo es algo que Purgito debe atender. Un rechazo de Discord (el bot sin permiso, un canal o mensaje borrado) indica configuración del servidor: se muestra aparte y no entra en la tasa de fallo, pero no se oculta. La latencia solo existe donde hay un temporizador instrumentado."),
  );

  const outcome = [
    { label: "Correctas", value: s.successes, color: COLORS.good },
    { label: "Fallos", value: s.errors, color: COLORS.critical },
    { label: "Rechazos de Discord", value: s.refused, color: COLORS.serious },
    { label: "Validaciones previas", value: s.rejected, color: COLORS.neutral },
  ];
  const total = outcome.reduce((a, o) => a + o.value, 0);
  const series = [
    { key: "errors", name: "Fallos", values: model.errors, color: COLORS.critical },
    { key: "refused", name: "Rechazos de Discord", values: model.refused, color: COLORS.serious },
  ];
  const anyBad = model.errors.some((v) => v) || model.refused.some((v) => v);
  const unit = model.step === "hour" ? "por hora" : "por día";
  root.append(
    h("div", { class: "grid grid-even" },
      panel({
        title: "Resultados",
        subtitle: "Reparto de las ejecuciones y entregas",
        body: total ? segmentedBar(outcome, { total }) : emptyState({ compact: true, title: "Sin resultados todavía", text: "Todavía no hay ejecuciones en este período." }),
      }),
      panel({
        title: "Fallos y rechazos",
        subtitle: `Número de eventos ${unit} · UTC`,
        legend: anyBad ? legend(series.map((i) => ({ name: i.name, color: i.color, kind: "box" }))) : null,
        body: anyBad ? timeChart({ times: model.times, step: model.step, kind: "columns", series, gaps: model.gaps, window: [model.start, model.end], annotations: model.annotations, label: `Fallos y rechazos de Discord ${unit}` }) : emptyState({ compact: true, title: model.hasUsage ? "Sin fallos ni rechazos" : "Nada que medir todavía", text: model.hasUsage ? "Ninguna ejecución terminó en fallo o rechazo en lo medido." : "Aparecerán cuando haya ejecuciones." }),
      }),
    ),
  );

  const rows = cur.features.filter((f) => f.uses).sort((a, b) => b.errors - a.errors || b.uses - a.uses);
  if (rows.length)
    root.append(h("section", { class: "panel" },
      h("header", { class: "panel-head" }, h("div", {}, h("h2", { class: "panel-title" }, "Calidad por función"), h("p", { class: "panel-sub" }, "Ordenado por fallos · p95 es el límite superior del tramo"))),
      dataTable(["Función", "Intentos", "Fallos", "Tasa de fallo", "Rechazos Discord", "Validaciones", "Latencia media", "p95", "Muestras"],
        rows.map((r) => [r.label, fmtInt(r.successes + r.errors), fmtInt(r.errors), fmtPct(r.error_pct), fmtInt(r.refused), fmtInt(r.rejected), fmtMs(r.mean_ms), r.p95_over_30000_ms ? "> 30 s" : r.p95_ms_upper_bound ? `≤ ${fmtMs(r.p95_ms_upper_bound)}` : "—", fmtInt(r.samples)]),
        { caption: "Calidad por función" })));
  return root;
}
