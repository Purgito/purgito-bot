// Escalas, ejes y geometría de los gráficos. Funciones puras (sin DOM).
import { fmtDay, fmtHour } from "./format.mjs";

export const HOUR = 3_600_000;
export const DAY = 24 * HOUR;

/** Paso "bonito" (1, 2, 5 × 10^k) para dividir [0, range] en ~target tramos. */
export function niceStep(range, target = 4) {
  const raw = range / Math.max(1, target);
  const pow = 10 ** Math.floor(Math.log10(raw));
  const frac = raw / pow;
  return (frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10) * pow;
}

/** Ticks para un eje que arranca en 0. Sin datos devuelve un eje 0–4 para no inventar escala. */
export function niceTicks(max, target = 4, integer = false) {
  if (!(max > 0)) return { max: 4, ticks: [0, 1, 2, 3, 4] };
  let step = niceStep(max, target);
  if (integer) step = Math.max(1, Math.ceil(step));
  const top = Math.ceil(max / step - 1e-9) * step;
  const ticks = [];
  for (let v = 0; v <= top + step / 1e6; v += step) ticks.push(Math.round(v * 1e9) / 1e9);
  return { max: top, ticks };
}

/** Ticks para un eje con parte negativa (min <= 0 <= max). */
export function niceTicksSigned(min, max, target = 4, integer = false) {
  const lo = Math.min(0, min);
  const hi = Math.max(0, max);
  if (!(hi > 0) && !(lo < 0)) return { min: 0, max: 4, ticks: [0, 1, 2, 3, 4] };
  let step = niceStep(hi - lo, target);
  if (integer) step = Math.max(1, Math.ceil(step));
  const bottom = Math.floor(lo / step + 1e-9) * step;
  const top = Math.ceil(hi / step - 1e-9) * step;
  const ticks = [];
  for (let v = bottom; v <= top + step / 1e6; v += step) ticks.push(Math.round(v * 1e9) / 1e9);
  return { min: bottom, max: top, ticks };
}

export function linear(d0, d1, r0, r1) {
  const span = d1 - d0;
  if (span === 0) return () => (r0 + r1) / 2;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Índice del valor más cercano a x en un arreglo ordenado. */
export function nearestIndex(sorted, x) {
  if (!sorted.length) return -1;
  let lo = 0;
  let hi = sorted.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid] <= x) lo = mid;
    else hi = mid;
  }
  return Math.abs(sorted[lo] - x) <= Math.abs(sorted[hi] - x) ? lo : hi;
}

/** Inicio de cada cubo de tiempo entre [start, end). */
export function buckets(startMs, endMs, step) {
  const size = step === "hour" ? HOUR : DAY;
  const first = Math.floor(startMs / size) * size;
  const out = [];
  for (let t = first; t < endMs; t += size) out.push(t);
  return out;
}

/** Marcas del eje X con etiquetas legibles; nunca más de maxTicks. */
export function timeTicks(t0, t1, step, maxTicks = 7) {
  const size = step === "hour" ? HOUR : DAY;
  const strides = step === "hour" ? [1, 2, 3, 4, 6, 12, 24, 48] : [1, 2, 3, 4, 5, 7, 10, 14, 30, 60];
  const span = Math.max(size, t1 - t0 + size);
  const stride = strides.find((s) => span / (s * size) <= maxTicks) ?? strides.at(-1);
  const unit = stride * size;
  const out = [];
  for (let t = Math.ceil(t0 / unit) * unit; t <= t1; t += unit) {
    const midnight = t % DAY === 0;
    out.push({
      t,
      label: step === "hour" && !midnight ? fmtHour(t) : fmtDay(t),
      major: step === "day" || midnight,
    });
  }
  return out.length ? out : [{ t: t0, label: step === "hour" ? fmtHour(t0) : fmtDay(t0), major: true }];
}

/** Segmentos continuos de una serie con huecos (null) para no unir lo que no se midió. */
export function segments(xs, ys) {
  const out = [];
  let current = [];
  ys.forEach((y, i) => {
    if (y == null || !Number.isFinite(y)) {
      if (current.length) out.push(current);
      current = [];
    } else current.push([xs[i], y]);
  });
  if (current.length) out.push(current);
  return out;
}

export const linePath = (points) =>
  points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");

export const areaPath = (points, baseline) =>
  points.length
    ? `${linePath(points)}L${points.at(-1)[0].toFixed(1)} ${baseline}L${points[0][0].toFixed(1)} ${baseline}Z`
    : "";

/** Rectángulo con las esquinas redondeadas solo en el extremo de datos (arriba o abajo). */
export function roundedBar(x, y, w, h, r, up = true) {
  const rad = Math.max(0, Math.min(r, w / 2, h));
  if (h <= 0 || w <= 0) return "";
  if (up)
    return `M${x} ${y + h}V${y + rad}Q${x} ${y} ${x + rad} ${y}H${x + w - rad}Q${x + w} ${y} ${x + w} ${y + rad}V${y + h}Z`;
  return `M${x} ${y}V${y + h - rad}Q${x} ${y + h} ${x + rad} ${y + h}H${x + w - rad}Q${x + w} ${y + h} ${x + w} ${y + h - rad}V${y}Z`;
}

/** Rango "bonito" alrededor de los datos, sin forzar el cero (p. ej. servidores instalados). */
export function niceRange(min, max, target = 4) {
  if (!(max > min)) {
    const pad = Math.max(1, Math.abs(max) * 0.05);
    min -= pad;
    max += pad;
  }
  const step = Math.max(1, niceStep(max - min, target));
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 1e6; v += step) ticks.push(Math.round(v * 1e9) / 1e9);
  return { min: lo, max: hi, ticks };
}
