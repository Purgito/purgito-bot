// Del informe JSON a series y textos de la interfaz. Puro (sin DOM): se prueba con Node.
import { fmtDuration, fmtInt, fmtNum, fmtPct } from "./format.mjs";
import { buckets, DAY, HOUR } from "./scale.mjs";

const ms = (v) => Date.parse(v);
const rowTime = (step) =>
  step === "hour" ? (r) => ms(r.at) : (r) => ms(`${r.day}T00:00:00Z`);

export function gapsMs(coverage) {
  return (coverage?.gaps || []).map((g) => ({ start: ms(g.start), end: ms(g.end) }));
}

/** Un cubo entero dentro de un hueco es "no medido" (null); fuera de los huecos, sin filas = 0 medido. */
export function fillSeries(rows, times, step, gaps, field) {
  const size = step === "hour" ? HOUR : DAY;
  const keyOf = rowTime(step);
  const byTime = new Map(rows.map((r) => [keyOf(r), r]));
  return times.map((t) => {
    const row = byTime.get(t);
    if (row) return row[field] ?? 0;
    return gaps.some((g) => g.start <= t && g.end >= t + size) ? null : 0;
  });
}

export function windowStep(startMs, endMs) {
  return endMs - startMs <= 72 * HOUR ? "hour" : "day";
}

export function buildModel(data, nowMs = Date.now()) {
  const start = ms(data.period.start);
  const end = ms(data.period.end);
  const cstart = ms(data.period.compare_start);
  const cend = ms(data.period.compare_end);
  const step = windowStep(start, end);
  const times = buckets(start, end, step);
  const ptimes = buckets(cstart, cend, step).slice(0, times.length);
  const cur = data.current;
  const prev = data.previous;
  const gaps = gapsMs(cur.coverage);
  const pgaps = gapsMs(prev.coverage);
  const rows = step === "hour" ? cur.hourly || [] : cur.daily;
  const prows = step === "hour" ? prev.hourly || [] : prev.daily;
  const pick = (field) => fillSeries(rows, times, step, gaps, field);
  const ppick = (field) => fillSeries(prows, ptimes, step, pgaps, field);

  const dayTime = (day) => ms(`${day}T00:00:00Z`);
  const inventory = data.inventory.map((r) => ({
    t: dayTime(r.day),
    installed: r.installed,
    observed_at: r.observed_at,
  }));
  const moves = new Map();
  for (const g of data.growth) {
    const t = dayTime(g.day);
    const m = moves.get(t) || { t, join: 0, leave: 0, rejoin: 0 };
    m[g.action] += g.n;
    moves.set(t, m);
  }
  const dayTimes = buckets(start, end, "day");
  const movement = (key) => dayTimes.map((t) => moves.get(t)?.[key] ?? 0);

  const coverageStart = data.coverage_started_at ? ms(data.coverage_started_at) : null;
  return {
    start,
    end,
    cstart,
    cend,
    step,
    times,
    ptimes,
    gaps,
    pgaps,
    uses: pick("uses"),
    active: pick("active"),
    errors: pick("errors"),
    successes: pick("successes"),
    refused: pick("refused"),
    prevUses: ppick("uses"),
    prevActive: ppick("active"),
    dayTimes,
    entries: movement("join"),
    exits: movement("leave"),
    rejoins: movement("rejoin"),
    inventory,
    annotations: data.annotations.map((a) => ({ ...a, t: ms(a.at) })),
    coverageStart,
    measuring: coverageStart != null,
    hasUsage: cur.summary.uses > 0,
    nowMs,
  };
}

/** Texto y tono de la variación; null si no se pidió comparación, objeto "none" si no hay base. */
export function deltaInfo(delta, goodWhenUp = null) {
  if (delta === undefined) return null;
  if (delta === null)
    return {
      kind: "none",
      text: "Sin comparación",
      title: "El período anterior no tiene cobertura suficiente para comparar.",
    };
  const sign = Math.sign(delta.difference);
  const arrow = sign > 0 ? "▲" : sign < 0 ? "▼" : "=";
  const abs = Math.abs(delta.difference);
  const tone =
    sign === 0 || goodWhenUp == null ? "neutral" : sign > 0 === goodWhenUp ? "good" : "bad";
  const partial = delta.status === "partial";
  const pct = delta.pct == null ? "" : ` (${fmtNum(Math.abs(delta.pct), 1)} %)`;
  return {
    kind: partial ? "partial" : "full",
    tone,
    text: `${partial ? "≈ " : ""}${arrow} ${fmtInt(abs)}${pct}`,
    title: partial
      ? "Solo lo observado: parte de un período no se midió. No es una estimación representativa."
      : "Frente al período anterior de igual duración.",
    spoken: `${sign > 0 ? "Sube" : sign < 0 ? "Baja" : "Sin cambio"}${sign ? ` ${fmtInt(abs)}${pct}` : ""} frente al período anterior${partial ? ", solo lo observado" : ""}`,
  };
}

/** Diferencia en puntos porcentuales de una tasa, respetando la política de comparación. */
export function rateDelta(cur, prev, comparison, goodWhenUp = false) {
  if (comparison.status === "not_comparable") return null;
  if (cur == null || prev == null) return { kind: "none", text: "Sin base comparable", title: "" };
  const diff = Math.round((cur - prev) * 100) / 100;
  const partial = comparison.status === "partial";
  const sign = Math.sign(diff);
  return {
    kind: partial ? "partial" : "full",
    tone: sign === 0 ? "neutral" : sign > 0 === goodWhenUp ? "good" : "bad",
    text: `${partial ? "≈ " : ""}${sign > 0 ? "▲" : sign < 0 ? "▼" : "="} ${fmtNum(Math.abs(diff), 1)} pp`,
    title: partial
      ? "Solo lo observado: parte de un período no se midió."
      : "Puntos porcentuales frente al período anterior.",
    spoken: `${sign > 0 ? "Sube" : sign < 0 ? "Baja" : "Sin cambio"} ${fmtNum(Math.abs(diff), 1)} puntos porcentuales`,
  };
}

export const COVERAGE_LABEL = {
  complete: "Cobertura completa",
  partial: "Cobertura parcial",
  unavailable: "Cobertura insuficiente",
};

/** Lo que hay que esperar para que cada métrica sea interpretable (estados vacíos útiles). */
export function milestones(coverageStartMs, nowMs, rangeDays) {
  if (coverageStartMs == null) return [];
  const startDay = Math.floor(coverageStartMs / DAY) * DAY;
  const at = (days) => startDay + days * DAY;
  const items = [
    { key: "d1", label: "Retención D1", at: at(2), note: "Primer día completo siguiente a la cohorte" },
    { key: "d7", label: "Retención D7", at: at(8), note: "Una semana tras la primera cohorte" },
    { key: "d28", label: "Retención D28", at: at(29), note: "Cuatro semanas tras la primera cohorte" },
    {
      key: "compare",
      label: `Comparar ${rangeDays} días con el período anterior`,
      at: at(2 * rangeDays),
      note: "Hace falta cobertura de los dos períodos",
    },
  ];
  return items.map((i) => ({ ...i, done: nowMs >= i.at, remaining: Math.max(0, i.at - nowMs) }));
}

/** Frase de estado de la portada. Solo afirma lo que los datos sostienen. */
export function statusSentence(data, model) {
  if (!model.measuring)
    return "Studio todavía no ha medido nada. La recopilación empieza cuando el bot se conecta a Discord.";
  const s = data.current.summary;
  const cov = data.current.coverage;
  const parts = [];
  if (!model.hasUsage && model.nowMs - model.coverageStart < 2 * HOUR)
    return `Studio empezó a medir hace ${fmtDuration((model.nowMs - model.coverageStart) / 1000)}. Todavía no hay uso registrado: las cifras irán apareciendo a medida que haya actividad.`;
  const installed = data.latest_inventory?.installed;
  if (installed != null) parts.push(`Purgito está en ${fmtInt(installed)} servidores.`);
  if (!model.hasUsage) {
    parts.push(
      cov.status === "complete"
        ? "No hay ejecuciones ni entregas registradas en este período."
        : `Todavía no hay uso registrado en lo medido (${fmtPct(cov.ratio * 100, 0)} del período).`,
    );
  } else {
    const observed = data.current.observed_communities;
    const share = observed ? ` (${fmtPct((100 * s.active) / observed, 0)} de las observadas)` : "";
    parts.push(
      `${fmtInt(s.active)} ${s.active === 1 ? "comunidad usó" : "comunidades usaron"} alguna función${share}, con ${fmtInt(s.uses)} ejecuciones y entregas.`,
    );
    parts.push(
      s.errors ? `${fmtInt(s.errors)} fallaron (${fmtPct(s.error_pct)}).` : "Sin fallos de ejecución.",
    );
  }
  if (cov.status !== "complete")
    parts.push(`Datos ${cov.status === "partial" ? "parciales" : "insuficientes"}: lo observado es un mínimo.`);
  return parts.join(" ");
}

export function sumGaps(coverage) {
  return fmtDuration(coverage?.gap_seconds ?? 0);
}
