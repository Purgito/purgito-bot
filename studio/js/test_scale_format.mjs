// Pruebas de las funciones puras: node studio/js/test_scale_format.mjs
import assert from "node:assert/strict";
import * as F from "./format.mjs";
import * as S from "./scale.mjs";

const t = (name, fn) => {
  fn();
  console.log("ok  ", name);
};

t("fmtInt: miles con punto desde 5 cifras y nunca inventa", () => {
  assert.equal(F.fmtInt(1234), "1234");
  assert.equal(F.fmtInt(12345), "12.345");
  assert.equal(F.fmtInt(null), "—");
  assert.equal(F.fmtInt(NaN), "—");
  assert.equal(F.fmtInt(0), "0");
});
t("fmtPct / fmtMs / fmtCompact", () => {
  assert.equal(F.fmtPct(12.34), `12,3${F.NBSP}%`);
  assert.equal(F.fmtPct(null), "—");
  assert.equal(F.fmtMs(420), `420${F.NBSP}ms`);
  assert.equal(F.fmtMs(2400), `2,4${F.NBSP}s`);
  assert.equal(F.fmtCompact(950), "950");
  assert.equal(F.fmtCompact(1234), `1,2${F.NBSP}K`);
  assert.equal(F.fmtCompact(12345), `12${F.NBSP}K`);
  assert.equal(F.fmtCompact(2_500_000), `2,5${F.NBSP}M`);
});
t("fmtDuration", () => {
  assert.equal(F.fmtDuration(45), `45${F.NBSP}s`);
  assert.equal(F.fmtDuration(720), `12${F.NBSP}min`);
  assert.equal(F.fmtDuration(3 * 3600 + 20 * 60), `3${F.NBSP}h 20${F.NBSP}min`);
  assert.equal(F.fmtDuration(2 * 86400 + 4 * 3600), `2${F.NBSP}d 4${F.NBSP}h`);
});
t("fechas en UTC y 'hace'", () => {
  const d = Date.UTC(2026, 10, 3, 0, 55);
  assert.equal(F.fmtDay(d), "3 nov");
  assert.equal(F.fmtHour(d), "00:55");
  assert.equal(F.fmtDateTime(d), "3 nov, 00:55 UTC");
  assert.equal(F.ago(d, d + 8000), `hace 8${F.NBSP}s`);
  assert.equal(F.ago(d, d + 3 * 3600_000), `hace 3${F.NBSP}h`);
  assert.equal(F.fromLocalInput("2026-11-03T00:55"), d);
  assert.equal(F.toLocalInput(d), "2026-11-03T00:55");
  assert.ok(Number.isNaN(F.fromLocalInput("")));
  assert.ok(Number.isNaN(F.fromLocalInput("mañana")));
  assert.ok(Number.isNaN(F.fromLocalInput(null)));
});
t("niceTicks: eje desde 0, sin escala inventada con datos vacíos", () => {
  assert.deepEqual(S.niceTicks(0).ticks, [0, 1, 2, 3, 4]);
  const { max, ticks } = S.niceTicks(87);
  assert.ok(max >= 87 && ticks[0] === 0 && ticks.at(-1) === max);
  assert.ok(S.niceTicks(3, 4, true).ticks.every(Number.isInteger));
  assert.ok(S.niceTicks(1234).ticks.length <= 7);
});
t("niceTicksSigned incluye el cero", () => {
  const { min, max, ticks } = S.niceTicksSigned(-3, 8, 4, true);
  assert.ok(min <= -3 && max >= 8 && ticks.includes(0));
});
t("linear y nearestIndex", () => {
  const x = S.linear(0, 10, 100, 200);
  assert.equal(x(5), 150);
  assert.equal(S.linear(5, 5, 0, 10)(5), 5);
  assert.equal(S.nearestIndex([0, 10, 20], 14), 1);
  assert.equal(S.nearestIndex([0, 10, 20], 16), 2);
  assert.equal(S.nearestIndex([], 1), -1);
  assert.equal(S.nearestIndex([7], 1000), 0);
});
t("buckets", () => {
  const start = Date.UTC(2026, 10, 3, 10, 30);
  assert.deepEqual(S.buckets(start, start + 3 * S.HOUR, "hour").length, 4);
  assert.equal(S.buckets(Date.UTC(2026, 10, 3), Date.UTC(2026, 10, 10), "day").length, 7);
});
t("timeTicks: máximo de marcas y etiquetas por paso", () => {
  const t0 = Date.UTC(2026, 10, 1);
  const days = S.timeTicks(t0, t0 + 27 * S.DAY, "day", 7);
  assert.ok(days.length <= 7 && days.length >= 3);
  const hours = S.timeTicks(t0, t0 + 47 * S.HOUR, "hour", 8);
  assert.ok(hours.length <= 8);
  assert.ok(hours.some((x) => x.major));
  assert.equal(S.timeTicks(t0, t0, "day", 7).length, 1);
});
t("segments corta en los huecos (no une lo que no se midió)", () => {
  const seg = S.segments([0, 1, 2, 3, 4], [1, 2, null, 4, 5]);
  assert.equal(seg.length, 2);
  assert.deepEqual(seg[1], [[3, 4], [4, 5]]);
  assert.deepEqual(S.segments([0], [null]), []);
});
t("paths", () => {
  assert.equal(S.linePath([[0, 10], [5, 20]]), "M0.0 10.0L5.0 20.0");
  assert.ok(S.areaPath([[0, 10], [5, 20]], 100).endsWith("Z"));
  assert.equal(S.areaPath([], 100), "");
  assert.equal(S.roundedBar(0, 0, 10, 0, 4), "");
  assert.ok(S.roundedBar(0, 0, 10, 20, 4).startsWith("M0 20"));
});
console.log("todas las pruebas puras pasaron");
