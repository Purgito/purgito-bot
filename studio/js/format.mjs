// Formato de cifras y fechas para la interfaz (es, siempre en UTC). Funciones puras.
export const NBSP = " ";
const INT = new Intl.NumberFormat("es");
const dec = (d) =>
  new Intl.NumberFormat("es", { minimumFractionDigits: 0, maximumFractionDigits: d });
const decCache = new Map();
const num = (d) => decCache.get(d) || (decCache.set(d, dec(d)), decCache.get(d));
const UTC = { timeZone: "UTC" };

const finite = (n) => typeof n === "number" && Number.isFinite(n);

export const fmtInt = (n) => (finite(n) ? INT.format(Math.round(n)) : "—");
export const fmtNum = (n, digits = 1) => (finite(n) ? num(digits).format(n) : "—");
export const fmtPct = (n, digits = 1) =>
  finite(n) ? `${num(digits).format(n)}${NBSP}%` : "—";

/** 1.234 -> "1,2 K" · 12.345 -> "12 K" · 1.234.567 -> "1,2 M". Solo para ejes y espacios cortos. */
export function fmtCompact(n) {
  if (!finite(n)) return "—";
  const abs = Math.abs(n);
  if (abs < 1000) return fmtInt(n);
  const [div, unit] = abs < 1e6 ? [1e3, "K"] : [1e6, "M"];
  const v = n / div;
  return `${num(Math.abs(v) < 10 ? 1 : 0).format(v)}${NBSP}${unit}`;
}

export function fmtMs(ms) {
  if (!finite(ms)) return "—";
  if (ms < 1000) return `${fmtInt(ms)}${NBSP}ms`;
  return `${num(ms < 10000 ? 1 : 0).format(ms / 1000)}${NBSP}s`;
}

/** Duración en segundos -> "45 s", "12 min", "3 h 20 min", "2 d 4 h". */
export function fmtDuration(seconds) {
  if (!finite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}${NBSP}s`;
  if (s < 3600) return `${Math.round(s / 60)}${NBSP}min`;
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.round((s % 3600) / 60);
    return m ? `${h}${NBSP}h ${m}${NBSP}min` : `${h}${NBSP}h`;
  }
  const d = Math.floor(s / 86400);
  const h = Math.round((s % 86400) / 3600);
  return h ? `${d}${NBSP}d ${h}${NBSP}h` : `${d}${NBSP}d`;
}

const ms = (v) => (typeof v === "number" ? v : Date.parse(v));
const f = (opts) => new Intl.DateTimeFormat("es", { ...UTC, ...opts });
const DAY = f({ day: "numeric", month: "short" });
const DAY_LONG = f({ day: "numeric", month: "long", year: "numeric" });
const HOUR = f({ hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const DATETIME = f({ day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

export const fmtDay = (v) => DAY.format(ms(v)).replace(".", "");
export const fmtDayLong = (v) => DAY_LONG.format(ms(v));
export const fmtHour = (v) => HOUR.format(ms(v));
export const fmtDateTime = (v) => `${DATETIME.format(ms(v)).replace(".", "")} UTC`;

/** "hace 8 s", "hace 3 min", "hace 2 h", "hace 4 d". */
export function ago(v, nowMs = Date.now()) {
  const sec = Math.max(0, Math.round((nowMs - ms(v)) / 1000));
  if (sec < 60) return `hace ${sec}${NBSP}s`;
  if (sec < 3600) return `hace ${Math.round(sec / 60)}${NBSP}min`;
  if (sec < 86400) return `hace ${Math.round(sec / 3600)}${NBSP}h`;
  return `hace ${Math.round(sec / 86400)}${NBSP}d`;
}

/** Valor de <input type=datetime-local> (UTC) <-> instante. */
export const toLocalInput = (v) => new Date(ms(v)).toISOString().slice(0, 16);
export const fromLocalInput = (value) =>
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value || "") ? Date.parse(`${value}:00Z`) : Number.NaN;

export const plural = (n, one, many) => `${fmtInt(n)} ${n === 1 ? one : many}`;
