// node studio/js/test_filters.mjs
import assert from "node:assert/strict";
import * as F from "./filters.mjs";
import { DAY, HOUR } from "./scale.mjs";

const t = (name, fn) => {
  fn();
  console.log("ok  ", name);
};
const now = Date.UTC(2026, 10, 4, 12, 30, 45, 500);

t("hash: ida y vuelta, y valores inválidos caen en el valor por defecto", () => {
  const f = { ...F.emptyFilters(), preset: "7d", version: "abc1234", feature: "chat", result: "ok", compare: false };
  const hash = F.buildHash("retention", f);
  assert.equal(hash, "#/retencion?p=7d&v=abc1234&f=chat&r=ok&cmp=0");
  assert.deepEqual(F.parseHash(hash), { view: "retention", filters: f });
  assert.equal(F.parseHash("#/no-existe?p=99d").view, "overview");
  assert.equal(F.parseHash("#/no-existe?p=99d").filters.preset, "");
  assert.equal(F.parseHash("").view, "overview");
  assert.equal(F.buildHash("overview", F.emptyFilters()), "#/resumen");
});
t("hash personalizado conserva fechas y comparación", () => {
  const f = { ...F.emptyFilters(), preset: "custom", start: "2026-10-01T00:00", end: "2026-10-08T00:00", compareEnd: "2026-10-01T00:00" };
  assert.deepEqual(F.parseHash(F.buildHash("growth", f)).filters, f);
});
t("rangeFor: hasta 72 h por horas y hasta ahora; más largo por días y hasta la medianoche UTC", () => {
  const midnight = Date.UTC(2026, 10, 4);
  const day = F.rangeFor({ preset: "24h" }, now);
  assert.equal(day.end, Math.floor(now / 1000) * 1000);
  assert.equal(day.end - day.start, DAY);
  assert.equal(F.rangeFor({ preset: "72h" }, now).end, Math.floor(now / 1000) * 1000);
  const week = F.rangeFor({ preset: "7d" }, now);
  assert.deepEqual([week.start, week.end], [midnight - 7 * DAY, midnight]);
  for (const id of ["28d", "90d", ""]) {
    const r = F.rangeFor({ preset: id }, now);
    assert.equal(r.end, midnight);
    assert.equal(r.start % DAY, 0);
  }
  assert.equal(F.rangeFor({ preset: "" }, now).end - F.rangeFor({ preset: "" }, now).start, 28 * DAY);
});
t("rangeFor 'since': primer día completo medido; por horas si hay menos de 3 días; tope de 90", () => {
  const midnight = Date.UTC(2026, 10, 4);
  const started = now - 10 * DAY - 17 * 60_000; // 25 oct 12:13
  const r = F.rangeFor({ preset: "since" }, now, started);
  assert.equal(r.start, Date.UTC(2026, 9, 26)); // primer día completo
  assert.equal(r.end, midnight);
  const young = now - 2 * DAY - 17 * 60_000; // menos de 3 días completos: por horas
  const y = F.rangeFor({ preset: "since" }, now, young);
  assert.equal(y.start, Math.floor(young / HOUR) * HOUR);
  assert.equal(y.end, Math.floor(now / 1000) * 1000);
  assert.equal(F.rangeFor({ preset: "since" }, now, now - 400 * DAY).start, midnight - 90 * DAY);
  const brand = F.rangeFor({ preset: "since" }, now, now - 60_000);
  assert.equal(brand.end - brand.start, 2 * HOUR);
  assert.equal(F.rangeFor({ preset: "since" }, now, null).end - F.rangeFor({ preset: "since" }, now, null).start, 28 * DAY);
});
t("rangeFor custom valida", () => {
  const ok = F.rangeFor({ preset: "custom", start: "2026-10-01T00:00", end: "2026-10-02T00:00" }, now);
  assert.equal(ok.end - ok.start, DAY);
  assert.throws(() => F.rangeFor({ preset: "custom", start: "", end: "" }, now), /fechas/);
  assert.throws(() => F.rangeFor({ preset: "custom", start: "2026-10-02T00:00", end: "2026-10-01T00:00" }, now), /posterior/);
  assert.throws(() => F.rangeFor({ preset: "custom", start: "2026-06-01T00:00", end: "2026-10-01T00:00" }, now), /90 días/);
  assert.throws(() => F.rangeFor({ preset: "custom", start: "2026-10-01T00:10", end: "2026-10-01T00:50" }, now), /hora completa/);
});
t("toQuery: filtros y comparación personalizada alineada a la hora", () => {
  const f = { ...F.emptyFilters(), preset: "custom", start: "2026-10-08T00:00", end: "2026-10-15T00:00", compareEnd: "2026-10-08T00:40", version: "v1", result: "error" };
  const q = F.toQuery(f, F.rangeFor(f, now));
  assert.equal(q.get("version"), "v1");
  assert.equal(q.get("result"), "error");
  assert.equal(q.get("feature"), null);
  assert.equal(q.get("compare_end"), "2026-10-08T00:00:00.000Z");
  assert.equal(q.get("compare_start"), "2026-10-01T00:00:00.000Z");
  assert.equal(F.toQuery({ ...F.emptyFilters(), preset: "7d" }, F.rangeFor({ preset: "7d" }, now)).get("compare_end"), null);
});
t("fetchKey ignora 'comparar' (solo presentación)", () => {
  const a = { ...F.emptyFilters(), preset: "7d" };
  assert.equal(F.fetchKey(a), F.fetchKey({ ...a, compare: false }));
  assert.notEqual(F.fetchKey(a), F.fetchKey({ ...a, version: "x" }));
});
console.log("todas las pruebas de filtros pasaron");
