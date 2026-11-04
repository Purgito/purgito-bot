// Resumen: el estado de Purgito de un vistazo y la puerta a cada detalle.
import { coverageStrip, legend, rankedBars, seriesTable, segmentedBar, sparkline, timeChart } from "../charts.mjs";
import { badge, emptyState, milestoneList, panel, stat } from "../components.mjs";
import { deltaInfo, milestones, rateDelta, statusSentence } from "../derive.mjs";
import { h } from "../dom.mjs";
import { fmtDay, fmtDuration, fmtInt, fmtMs, fmtPct, ago } from "../format.mjs";

export const COLORS = {
  series1: "var(--series-1)",
  prev: "var(--prev)",
  good: "var(--good)",
  critical: "var(--critical)",
  serious: "var(--serious)",
  neutral: "var(--prev)",
};

export function usageSeries(model, comparison, data) {
  const list = [{ key: "uses", name: "Período actual", values: model.uses, color: COLORS.series1, area: true }];
  const prevHasData = data.previous.coverage.ratio > 0 && model.prevUses.some((v) => v);
  if (comparison.status !== "not_comparable" && prevHasData)
    list.push({ key: "prev", name: "Período anterior", values: model.prevUses, color: COLORS.prev, muted: true });
  return list;
}

export function overview({ data, model, nav, openCoverage }) {
  const cur = data.current;
  const s = cur.summary;
  const partial = cur.coverage.status !== "complete";
  const root = h("div", { class: "stack" });
  root.append(h("p", { class: "lead" }, statusSentence(data, model)));

  if (!model.measuring) {
    root.append(
      emptyState({
        title: "Todavía no hay mediciones",
        text: "Studio empieza a guardar datos cuando el bot se conecta a Discord con la recopilación activada. Cuando haya un primer volcado, esta portada se llena sola.",
      }),
    );
    return root;
  }

  const inv = data.latest_inventory;
  const attempts = s.successes + s.errors;
  root.append(
    h("div", { class: "kpis" },
      stat({
        hero: true,
        label: "Comunidades activas",
        value: fmtInt(s.active),
        delta: deltaInfo(data.delta.active, true),
        trend: sparkline(model.active, { label: "Comunidades activas por tramo", width: 140, height: 40 }),
        note: cur.observed_communities ? `de ${fmtInt(cur.observed_communities)} observadas` : "Sin inventario del período",
        partial,
      }),
      stat({
        label: "Servidores instalados",
        value: fmtInt(inv?.installed),
        note: inv ? `Inventario del ${fmtDay(inv.observed_at)}` : "Sin inventario",
        trend: model.inventory.length > 1 ? sparkline(model.inventory.map((i) => i.installed), { label: "Servidores instalados por día" }) : null,
      }),
      stat({
        label: "Ejecuciones y entregas",
        value: fmtInt(s.uses),
        delta: deltaInfo(data.delta.uses, true),
        trend: sparkline(model.uses, { label: "Ejecuciones y entregas por tramo" }),
        partial,
      }),
      stat({
        label: "Tasa de fallo",
        value: fmtPct(s.error_pct),
        delta: rateDelta(s.error_pct, data.previous.summary.error_pct, data.comparison, false),
        note: attempts ? `${fmtInt(s.errors)} fallos en ${fmtInt(attempts)} intentos` : "Sin intentos registrados",
      }),
      stat({
        label: "Latencia media",
        value: fmtMs(s.mean_ms),
        note: s.p95_ms_upper_bound ? `p95 ≤ ${fmtMs(s.p95_ms_upper_bound)}` : s.p95_over_30000_ms ? "p95 > 30 s" : "Sin muestras de latencia",
      }),
    ),
  );

  const unit = model.step === "hour" ? "por hora" : "por día";
  const series = usageSeries(model, data.comparison, data);
  const usageBody = model.hasUsage
    ? timeChart({ times: model.times, step: model.step, series, gaps: model.gaps, window: [model.start, model.end], annotations: model.annotations, label: `Ejecuciones y entregas ${unit}`, height: 300 })
    : emptyState({
        compact: true,
        title: "Sin uso registrado en lo medido",
        text: cur.coverage.status === "complete" ? "Nadie ha ejecutado comandos ni recibido entregas en este período." : "Una cobertura incompleta no permite afirmar que no hubo uso.",
      });
  const top = cur.features.filter((f) => f.uses).sort((a, b) => b.uses - a.uses).slice(0, 5);
  root.append(
    h("div", { class: "grid grid-wide" },
      panel({
        title: "Uso en el período",
        subtitle: `Ejecuciones y entregas ${unit} · UTC`,
        legend: series.length > 1 ? legend(series.map((i) => ({ name: i.name, color: i.color }))) : null,
        body: usageBody,
        table: model.hasUsage ? seriesTable(model.times, model.step, series) : null,
      }),
      panel({
        title: "Qué se usa",
        subtitle: "Funciones con más ejecuciones",
        body: top.length
          ? h("div", {}, rankedBars(top.map((f) => ({ label: f.label, hint: `${fmtInt(f.served)} ${f.served === 1 ? "comunidad" : "comunidades"}`, value: f.uses }))), h("button", { type: "button", class: "btn btn-link", onclick: () => nav("features") }, "Ver todas las funciones"))
          : emptyState({ compact: true, title: "Sin funciones usadas todavía", text: "Aparecerán aquí en cuanto haya ejecuciones o entregas." }),
      }),
    ),
  );

  const outcome = [
    { label: "Correctas", value: s.successes, color: COLORS.good, note: "Terminaron bien" },
    { label: "Fallos", value: s.errors, color: COLORS.critical, note: "Errores que Purgito debe atender" },
    { label: "Rechazos de Discord", value: s.refused, color: COLORS.serious, note: "Permisos del bot, canal o mensaje borrado: no cuentan como fallo" },
    { label: "Validaciones previas", value: s.rejected, color: COLORS.neutral, note: "Permisos de quien invoca, argumentos o cooldown" },
  ];
  const total = outcome.reduce((a, o) => a + o.value, 0);
  const col = data.collector;
  const cov = cur.coverage;
  const mile = milestones(model.coverageStart, model.nowMs, Math.round((model.end - model.start) / 86_400_000) || 1).filter((m) => !m.done);
  root.append(
    h("div", { class: "grid grid-even" },
      panel({
        title: "Resultados",
        subtitle: "Cómo terminaron las ejecuciones y entregas",
        body: total ? h("div", {}, segmentedBar(outcome, { total }), h("button", { type: "button", class: "btn btn-link", onclick: () => nav("reliability") }, "Ver calidad en detalle")) : emptyState({ compact: true, title: "Sin resultados que mostrar", text: "Todavía no hay ejecuciones en este período." }),
      }),
      panel({
        title: "Estado de la medición",
        subtitle: "Qué parte del período está medida",
        body: h("div", { class: "measure" },
          coverageStrip(cov, model.start, model.end, { label: `Cobertura del período: ${fmtPct(cov.ratio * 100)}` }),
          h("dl", { class: "facts" },
            h("div", {}, h("dt", {}, "Cobertura"), h("dd", {}, fmtPct(cov.ratio * 100), cov.gap_count ? ` · ${cov.gap_count} ${cov.gap_count === 1 ? "hueco" : "huecos"} (${fmtDuration(cov.gap_seconds)})` : "")),
            h("div", {}, h("dt", {}, "Último volcado"), h("dd", {}, col.last_flush ? ago(col.last_flush, model.nowMs) : "Ninguno todavía")),
            h("div", {}, h("dt", {}, "Descartes"), h("dd", {}, col.dropped ? `${fmtInt(col.dropped)} registros` : "Ninguno")),
            h("div", {}, h("dt", {}, "Versión"), h("dd", {}, col.version)),
            h("div", {}, h("dt", {}, "Retención"), h("dd", {}, `${col.retention_days} días`)),
          ),
          h("button", { type: "button", class: "btn btn-link", onclick: openCoverage }, "Ver detalle de cobertura"),
          mile.length ? h("div", { class: "measure-next" }, h("h3", {}, "Cuándo habrá más datos"), milestoneList(mile.slice(0, 3), model.nowMs)) : null,
        ),
      }),
    ),
  );
  return root;
}

export { badge };
