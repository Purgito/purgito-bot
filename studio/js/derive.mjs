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
  const cur = data.current;
  const prev = data.previous;
  // Un bot en ejecución anterior a la serie por horas no envía `hourly`: dibujar horas sin datos mostraría
  // una línea plana en cero con uso real. En ese caso se degrada a días y se avisa (`degraded`).
  const wantsHours = windowStep(start, end) === "hour";
  const hasHourly = Array.isArray(cur.hourly) && Array.isArray(prev.hourly);
  const step = wantsHours && hasHourly ? "hour" : "day";
  const times = buckets(start, end, step);
  const ptimes = buckets(cstart, cend, step).slice(0, times.length);
  const gaps = gapsMs(cur.coverage);
  const pgaps = gapsMs(prev.coverage);
  const rows = step === "hour" ? cur.hourly : cur.daily;
  const prows = step === "hour" ? prev.hourly : prev.daily;
  const pick = (field) => fillSeries(rows, times, step, gaps, field);
  const ppick = (field) => fillSeries(prows, ptimes, step, pgaps, field);

  const dayTime = (day) => ms(`${day}T00:00:00Z`);
  const inventory = data.inventory.map((r) => ({
    t: dayTime(r.day),
    installed: r.installed,
    observed_at: r.observed_at,
    version: r.version,
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
    degraded: wantsHours && !hasHourly,
    times,
    ptimes,
    gaps,
    pgaps,
    uses: pick("uses"),
    active: pick("active"),
    errors: pick("errors"),
    successes: pick("successes"),
    refused: pick("refused"),
    rejected: pick("rejected"),
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
  // Por debajo de lo que se muestra (0,05 pp) no hay cambio que enseñar: nunca «▲ 0 pp».
  const sign = Math.abs(diff) < 0.05 ? 0 : Math.sign(diff);
  return {
    kind: partial ? "partial" : "full",
    tone: sign === 0 ? "neutral" : sign > 0 === goodWhenUp ? "good" : "bad",
    text: sign === 0 ? `${partial ? "≈ " : ""}= sin cambio` : `${partial ? "≈ " : ""}${sign > 0 ? "▲" : "▼"} ${fmtNum(Math.abs(diff), 1)} pp`,
    title: partial
      ? "Solo lo observado: parte de un período no se midió."
      : "Puntos porcentuales frente al período anterior.",
    spoken: sign === 0 ? "Sin cambio frente al período anterior" : `${sign > 0 ? "Sube" : "Baja"} ${fmtNum(Math.abs(diff), 1)} puntos porcentuales`,
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
      label: `Comparar ${rangeDays} ${rangeDays === 1 ? "día" : "días"} con el período anterior`,
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

/* -------------------------------------------------------------- calidad */

/**
 * Señal compacta de fiabilidad. Describe, no diagnostica: dos fallos no son un incidente.
 * tone: none (sin intentos) · calm · watch (≥ 1 % con muestra suficiente) · attention (≥ 5 % con ≥ 50 intentos).
 */
export function qualitySignal(summary) {
  const attempts = (summary.successes || 0) + (summary.errors || 0);
  if (!attempts) return { tone: "none", attempts, text: "Sin intentos registrados" };
  const pct = summary.error_pct ?? 0;
  if (!summary.errors) return { tone: "calm", attempts, text: "Sin fallos en lo medido" };
  const small = attempts < 50;
  const tone = small ? "calm" : pct >= 5 ? "attention" : pct >= 1 ? "watch" : "calm";
  const text = small
    ? `${fmtInt(summary.errors)} ${summary.errors === 1 ? "fallo" : "fallos"} en ${fmtInt(attempts)} intentos`
    : tone === "attention" ? "Fallos por encima del 5 %" : tone === "watch" ? "Fallos entre el 1 % y el 5 %" : "Fallos por debajo del 1 %";
  return { tone, attempts, small, text };
}

/** Muestra mínima por debajo de la cual una tasa se marca como poco fiable. */
export const SMALL_SAMPLE = 30;

/** Intervalo del histograma que contiene el p95 [inferior, superior] en ms, o null. */
const P95_BOUNDS = [25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000];
export function p95Interval(row) {
  if (row.p95_over_30000_ms) return [30000, null];
  const up = row.p95_ms_upper_bound;
  if (!up) return null;
  const i = P95_BOUNDS.indexOf(up);
  return [i > 0 ? P95_BOUNDS[i - 1] : 0, up];
}

/* -------------------------------------------------------------- funciones */

/** Separa lo usado, lo instrumentado sin uso observado y lo no instrumentado (nunca se mezclan). */
export function featureGroups(features) {
  const used = features.filter((f) => f.uses > 0).sort((a, b) => b.uses - a.uses);
  const idle = features.filter((f) => f.coverage !== "not_instrumented" && !(f.uses > 0));
  const blind = features.filter((f) => f.coverage === "not_instrumented");
  const total = used.reduce((a, f) => a + f.uses, 0);
  return { used, idle, blind, total };
}

/** Comandos del período agrupados por función según el catálogo del bot ({source|command: feature}). */
export function commandFeature(catalog = []) {
  const map = new Map(catalog.map((c) => [`${c.source}|${c.command}`, c.feature]));
  return (c) => map.get(`${c.source}|${c.command}`) || null;
}

/* ---------------------------------------------------------------- versiones */

/**
 * Tramos de días en que cada versión aparece en el inventario diario. Es una aproximación por día
 * (el inventario se toma una vez al día), no la hora exacta del despliegue.
 */
export function versionLanes(inventory, annotations = []) {
  const lanes = new Map();
  for (const row of [...inventory].sort((a, b) => a.t - b.t)) {
    if (!row.version) continue;
    const lane = lanes.get(row.version) || { version: row.version, spans: [], first: row.t, last: row.t };
    const prev = lane.spans.at(-1);
    if (prev && row.t - prev.end <= DAY) prev.end = row.t;
    else lane.spans.push({ start: row.t, end: row.t });
    lane.last = row.t;
    lanes.set(row.version, lane);
  }
  for (const a of annotations) {
    if (a.kind === "release" && a.version && lanes.has(a.version)) lanes.get(a.version).release = a;
  }
  return [...lanes.values()].sort((a, b) => a.first - b.first);
}

/* --------------------------------------------------------------- retención */

/** Media ponderada por tamaño de cohorte, solo con cohortes maduras. */
export function retentionSummary(rows, metricKey) {
  return [1, 7, 28].map((days) => {
    let weight = 0;
    let acc = 0;
    let n = 0;
    let baseline = false;
    for (const r of rows) {
      const hz = r.horizons.find((x) => x.days === days);
      if (hz?.eligible && hz[metricKey] != null) {
        weight += r.size;
        acc += hz[metricKey] * r.size;
        n += 1;
        baseline ||= Boolean(r.baseline);
      }
    }
    return { days, value: weight ? acc / weight : null, n, weight, baseline };
  });
}

/**
 * Cuándo podrá leerse un horizonte no maduro: el día objetivo tiene que terminar. Si ya terminó y aun así
 * no es elegible, faltó cobertura continua o inventario (no se volverá elegible).
 */
export function horizonState(cohortDay, days, nowMs) {
  const target = ms(`${cohortDay}T00:00:00Z`) + days * DAY;
  const ready = target + DAY;
  return ready > nowMs ? { pending: true, at: ready } : { pending: false, at: ready };
}

/* -------------------------------------------------------------- comunidades */

export function movementTotals(model) {
  const sum = (list) => list.reduce((a, b) => a + b, 0);
  const entries = sum(model.entries);
  const exits = sum(model.exits);
  const rejoins = sum(model.rejoins);
  return { entries, exits, rejoins, net: entries + rejoins - exits, any: entries + exits + rejoins > 0 };
}

/* ---------------------------------------------------------------- comandos */

/** Muestra mínima por comando para hablar de «dependencia» sin matices. */
export const SMALL_COMMAND_SAMPLE = 20;

/** Identidad de un comando: la misma palabra por prefijo y por slash son dos entradas distintas. */
export const commandId = (c) => `${c.source}:${c.command}`;

/** Lo que el usuario escribe delante: `!` para prefijo (el valor por defecto) y `/` para slash. */
export const commandGlyph = (source) => (source === "prefix" ? "!" : source === "slash" ? "/" : "");

/**
 * De cuántos servidores depende un comando. Solo informa de la forma del reparto (cuántos y qué
 * fracción de los intentos aporta el mayor); nunca de cuáles son.
 */
export function concentration(c) {
  const guilds = c.guilds || 0;
  const shares = c.top_shares || [];
  if (!c.uses || !guilds || !shares.length) return { kind: "none", guilds: 0, top1: null, top3: null, small: true };
  const top1 = shares[0];
  const top3 = Math.min(1, shares.slice(0, 3).reduce((a, b) => a + b, 0));
  const kind = guilds === 1 ? "single" : top1 >= 0.5 ? "concentrated" : "spread";
  return { kind, guilds, top1, top3, small: c.uses < SMALL_COMMAND_SAMPLE };
}

/** Cambio frente al período anterior: respeta la política de comparación y marca lo que no existía. */
export function commandChange(c, comparison) {
  if (!comparison || comparison.status === "not_comparable") return null;
  const prev = c.previous?.uses ?? 0;
  if (!prev) return c.uses ? { kind: "new" } : null;
  const difference = c.uses - prev;
  return { kind: "delta", difference, info: deltaInfo({ difference, pct: Math.round((1000 * difference) / prev) / 10, status: comparison.status }, null) };
}

const SORTS = {
  uses: (a, b) => b.uses - a.uses,
  served: (a, b) => b.served - a.served || b.uses - a.uses,
  change: (a, b) => (b.uses - (b.previous?.uses ?? 0)) - (a.uses - (a.previous?.uses ?? 0)) || b.uses - a.uses,
  errors: (a, b) => (b.error_pct ?? -1) - (a.error_pct ?? -1) || b.errors - a.errors || b.uses - a.uses,
  name: (a, b) => a.command.localeCompare(b.command, "es") || a.source.localeCompare(b.source),
};
export const COMMAND_SORTS = Object.keys(SORTS);

/** Filtra por texto (nombre o función) y por tipo de entrada, y ordena. No modifica la entrada. */
export function rankCommands(rows, { query = "", source = "", sort = "uses", featureLabel = (f) => f } = {}) {
  const q = query.trim().toLowerCase().replace(/^[!/]/, "");
  const match = (c) => (!source || c.source === source)
    && (!q || c.command.toLowerCase().includes(q) || String(featureLabel(c.feature) ?? "").toLowerCase().includes(q));
  return rows.filter(match).sort(SORTS[sort] || SORTS.uses);
}

/** Registrados en el catálogo del bot sin ninguna ejecución en el período, agrupados por función. */
export function unusedCommands(catalog = [], used = []) {
  const seen = new Set(used.map(commandId));
  return catalog.filter((c) => !seen.has(commandId(c)));
}

/** Series de un comando alineadas al eje del gráfico: lo que está en un hueco de cobertura es null. */
export function commandSeries(row, times, step, gaps) {
  const rows = row.series || [];
  const ok = fillSeries(rows.map((r) => ({ ...r, ok: r.uses - r.errors })), times, step, gaps, "ok");
  return { ok, errors: fillSeries(rows, times, step, gaps, "errors"), uses: fillSeries(rows, times, step, gaps, "uses"), served: fillSeries(rows, times, step, gaps, "served") };
}
