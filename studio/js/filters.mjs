// Filtros y vista actual <-> URL (#/vista?p=7d&v=...), y su traducción a parámetros de la API.
import { fromLocalInput } from "./format.mjs";
import { DAY, HOUR } from "./scale.mjs";

export const VIEWS = {
  overview: { slug: "resumen", title: "Resumen", icon: "overview", group: "general" },
  growth: { slug: "comunidades", title: "Comunidades", icon: "growth", group: "product" },
  retention: { slug: "retencion", title: "Retención", icon: "retention", group: "product" },
  features: { slug: "funciones", title: "Funciones", icon: "features", group: "product" },
  commands: { slug: "comandos", title: "Comandos", icon: "commands", group: "product" },
  reliability: { slug: "calidad", title: "Calidad", icon: "reliability", group: "operation" },
  versions: { slug: "versiones", title: "Versiones", icon: "versions", group: "operation" },
  updates: { slug: "actualizaciones", title: "Actualizaciones", icon: "updates", group: "operation" },
};
export const GROUPS = { general: "Visión general", product: "Producto y adopción", operation: "Operación y evolución" };
const BY_SLUG = Object.fromEntries(Object.entries(VIEWS).map(([k, v]) => [v.slug, k]));

export const PRESETS = [
  { id: "24h", label: "24 h", ms: 24 * HOUR },
  { id: "72h", label: "3 días", ms: 72 * HOUR },
  { id: "7d", label: "7 días", ms: 7 * DAY },
  { id: "28d", label: "28 días", ms: 28 * DAY },
  { id: "90d", label: "90 días", ms: 90 * DAY },
];
const PRESET_IDS = new Set([...PRESETS.map((p) => p.id), "since", "custom"]);

export const emptyFilters = () => ({ preset: "", start: "", end: "", compareEnd: "", version: "", feature: "", result: "", compare: true, cmd: "" });

export function parseHash(hash) {
  const [path, query = ""] = String(hash || "").replace(/^#\/?/, "").split("?");
  const view = BY_SLUG[path] || "overview";
  const q = new URLSearchParams(query);
  const filters = emptyFilters();
  const preset = q.get("p") || "";
  filters.preset = PRESET_IDS.has(preset) ? preset : "";
  filters.version = q.get("v") || "";
  filters.feature = q.get("f") || "";
  filters.result = q.get("r") || "";
  filters.start = q.get("s") || "";
  filters.end = q.get("e") || "";
  filters.compareEnd = q.get("c") || "";
  filters.compare = q.get("cmp") !== "0";
  filters.cmd = q.get("k") || "";
  return { view, filters };
}

export function buildHash(view, filters) {
  const q = new URLSearchParams();
  if (filters.preset) q.set("p", filters.preset);
  if (filters.preset === "custom") {
    q.set("s", filters.start);
    q.set("e", filters.end);
    if (filters.compareEnd) q.set("c", filters.compareEnd);
  }
  for (const [key, value] of [["v", filters.version], ["f", filters.feature], ["r", filters.result]]) if (value) q.set(key, value);
  if (!filters.compare) q.set("cmp", "0");
  // El comando elegido solo viaja en su propia vista; no ensucia los enlaces de las demás.
  if (view === "commands" && filters.cmd) q.set("k", filters.cmd);
  const query = q.toString();
  return `#/${VIEWS[view].slug}${query ? `?${query}` : ""}`;
}

/** Lo que obliga a volver a pedir datos (comparar o no es solo de presentación). */
export const fetchKey = (f) => JSON.stringify([f.preset, f.preset === "custom" ? [f.start, f.end, f.compareEnd] : null, f.version, f.feature, f.result]);

const floorHour = (t) => Math.floor(t / HOUR) * HOUR;
const floorDay = (t) => Math.floor(t / DAY) * DAY;
const ceilDay = (t) => Math.ceil(t / DAY) * DAY;

/**
 * Ventana [start, end] en ms. Hasta 72 h se mide por horas y termina ahora. Las más largas se miden
 * por días y terminan en la medianoche UTC anterior: así ningún día del gráfico queda a medias y un
 * día parcial no parece una caída. «Desde el inicio» arranca en el primer día completo medido.
 */
export function rangeFor(f, nowMs, coverageStartMs = null) {
  const now = Math.floor(nowMs / 1000) * 1000;
  if (f.preset === "custom") {
    const start = fromLocalInput(f.start);
    const to = fromLocalInput(f.end);
    if (!Number.isFinite(start) || !Number.isFinite(to)) throw new Error("Indica las fechas de inicio y fin.");
    if (to <= start) throw new Error("El fin del período debe ser posterior al inicio.");
    if (to - start > 90 * DAY) throw new Error("El período máximo es de 90 días.");
    if (floorHour(to) <= floorHour(start)) throw new Error("Selecciona al menos una hora completa.");
    return { start, end: to };
  }
  const byDays = (days) => ({ start: floorDay(now) - days * DAY, end: floorDay(now) });
  if (f.preset === "since") {
    if (coverageStartMs == null) return byDays(28);
    const first = Math.max(ceilDay(coverageStartMs), floorDay(now) - 90 * DAY);
    if (floorDay(now) - first > 72 * HOUR) return { start: first, end: floorDay(now) };
    return { start: Math.min(floorHour(coverageStartMs), now - 2 * HOUR), end: now };
  }
  const preset = PRESETS.find((p) => p.id === f.preset) || PRESETS.find((p) => p.id === "28d");
  return preset.ms > 72 * HOUR ? byDays(preset.ms / DAY) : { start: now - preset.ms, end: now };
}

export function toQuery(f, range) {
  const q = new URLSearchParams({ start: new Date(range.start).toISOString(), end: new Date(range.end).toISOString() });
  for (const [key, value] of [["version", f.version], ["feature", f.feature], ["result", f.result]]) if (value) q.set(key, value);
  if (f.preset === "custom" && f.compareEnd) {
    const to = floorHour(fromLocalInput(f.compareEnd));
    q.set("compare_end", new Date(to).toISOString());
    q.set("compare_start", new Date(to - (floorHour(range.end) - floorHour(range.start))).toISOString());
  }
  return q;
}
