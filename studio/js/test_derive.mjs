// node studio/js/test_derive.mjs
import assert from "node:assert/strict";
import * as D from "./derive.mjs";
import { DAY, HOUR } from "./scale.mjs";

const t = (name, fn) => {
  fn();
  console.log("ok  ", name);
};
const day0 = Date.UTC(2026, 10, 1);
const iso = (ms) => new Date(ms).toISOString();

t("fillSeries: sin filas = 0 si se midió, null dentro de un hueco", () => {
  const times = [0, 1, 2, 3].map((i) => day0 + i * DAY);
  const rows = [{ day: "2026-11-01", uses: 5 }, { day: "2026-11-04", uses: 2 }];
  const gaps = [{ start: day0 + DAY, end: day0 + 2 * DAY }];
  assert.deepEqual(D.fillSeries(rows, times, "day", gaps, "uses"), [5, null, 0, 2]);
  assert.deepEqual(D.fillSeries([], times, "day", [], "uses"), [0, 0, 0, 0]);
});
t("fillSeries por horas", () => {
  const times = [0, 1, 2].map((i) => day0 + i * HOUR);
  const rows = [{ at: iso(day0 + HOUR), uses: 3 }];
  assert.deepEqual(D.fillSeries(rows, times, "hour", [], "uses"), [0, 3, 0]);
});
t("windowStep: horas hasta 72 h, días después", () => {
  assert.equal(D.windowStep(0, 72 * HOUR), "hour");
  assert.equal(D.windowStep(0, 72 * HOUR + 1), "day");
});

const base = (over = {}) => {
  const cov = { status: "complete", ratio: 1, gaps: [], gap_count: 0, gap_seconds: 0, dropped: 0 };
  const win = (extra = {}) => ({
    summary: { uses: 0, active: 0, errors: 0, error_pct: null },
    daily: [], hourly: [], coverage: cov, observed_communities: 0, ...extra,
  });
  return {
    period: { start: iso(day0), end: iso(day0 + 3 * DAY), compare_start: iso(day0 - 3 * DAY), compare_end: iso(day0) },
    current: win(), previous: win(), inventory: [], growth: [], annotations: [],
    coverage_started_at: iso(day0), latest_inventory: { installed: 125 },
    comparison: { status: "comparable" }, ...over,
  };
};

t("buildModel: días, movimientos e inventario sin interpolar", () => {
  const data = base({
    growth: [{ day: "2026-11-02", action: "join", n: 2 }, { day: "2026-11-02", action: "leave", n: 1 }],
    inventory: [{ day: "2026-11-01", installed: 120, observed_at: iso(day0) }],
    annotations: [{ id: "a", at: iso(day0 + HOUR), title: "v1", kind: "release" }],
  });
  const m = D.buildModel(data, day0 + DAY);
  assert.equal(m.step, "hour");
  assert.equal(m.times.length, 72);
  assert.deepEqual(m.entries, [0, 2, 0]);
  assert.deepEqual(m.exits, [0, 1, 0]);
  assert.equal(m.inventory.length, 1);
  assert.equal(m.annotations[0].t, day0 + HOUR);
  assert.equal(m.measuring, true);
  assert.equal(D.buildModel(base({ coverage_started_at: null })).measuring, false);
});
t("buildModel: ventana larga usa cubos diarios", () => {
  const data = base();
  data.period.end = iso(day0 + 10 * DAY);
  data.period.compare_start = iso(day0 - 10 * DAY);
  assert.equal(D.buildModel(data).times.length, 10);
});
t("deltaInfo: tono según si subir es bueno, y 'parcial' se declara", () => {
  assert.equal(D.deltaInfo(undefined), null);
  assert.equal(D.deltaInfo(null).kind, "none");
  const up = D.deltaInfo({ difference: 12, pct: 31.25, status: "comparable" }, true);
  assert.equal(up.tone, "good");
  assert.ok(up.text.startsWith("▲ 12"));
  assert.equal(D.deltaInfo({ difference: 12, pct: 5, status: "comparable" }, false).tone, "bad");
  assert.equal(D.deltaInfo({ difference: 12, pct: 5, status: "comparable" }, null).tone, "neutral");
  const partial = D.deltaInfo({ difference: -3, pct: null, status: "partial" }, true);
  assert.ok(partial.text.startsWith("≈ ▼ 3"));
  assert.equal(partial.kind, "partial");
  assert.match(partial.spoken, /solo lo observado/);
  assert.equal(D.deltaInfo({ difference: 0, pct: 0, status: "comparable" }, true).tone, "neutral");
});
t("rateDelta respeta la política de comparación", () => {
  assert.equal(D.rateDelta(1, 2, { status: "not_comparable" }), null);
  assert.equal(D.rateDelta(null, 2, { status: "comparable" }).kind, "none");
  assert.equal(D.rateDelta(3, 1, { status: "comparable" }).tone, "bad");
  assert.equal(D.rateDelta(1, 3, { status: "comparable" }).tone, "good");
});
t("milestones: fechas deterministas y estado", () => {
  const items = D.milestones(day0 + 3600_000, day0 + 5 * DAY, 7);
  assert.equal(items.find((i) => i.key === "d1").at, day0 + 2 * DAY);
  assert.equal(items.find((i) => i.key === "d1").done, true);
  assert.equal(items.find((i) => i.key === "d7").done, false);
  assert.equal(items.find((i) => i.key === "compare").at, day0 + 14 * DAY);
  assert.deepEqual(D.milestones(null, 0, 7), []);
});
t("statusSentence: sin medición, sin uso y con uso", () => {
  const none = base({ coverage_started_at: null });
  assert.match(D.statusSentence(none, D.buildModel(none)), /todavía no ha medido nada/);
  const fresh = base();
  const young = D.buildModel(fresh, day0 + 20 * 60_000);
  assert.match(D.statusSentence(fresh, young), /empezó a medir hace 20.min.*irán apareciendo/);
  const empty = base();
  const m = D.buildModel(empty, day0 + 5 * DAY);
  assert.match(D.statusSentence(empty, m), /125 servidores.*No hay ejecuciones/);
  const used = base();
  used.current.summary = { uses: 40, active: 9, errors: 2, error_pct: 5 };
  used.current.observed_communities = 125;
  const sentence = D.statusSentence(used, D.buildModel(used));
  assert.match(sentence, /9 comunidades usaron.*7\s%.*40 ejecuciones/);
  assert.match(sentence, /2 fallaron/);
  used.current.coverage = { ...used.current.coverage, status: "partial", ratio: 0.93 };
  assert.match(D.statusSentence(used, D.buildModel(used)), /parciales: lo observado es un mínimo/);
});
t("backend sin serie por horas: degrada a días con aviso, sin inventar una línea plana", () => {
  const old = base({ growth: [] });
  old.current.daily = [{ day: "2026-11-01", uses: 7, active: 2, errors: 0, successes: 7, refused: 0 }];
  delete old.current.hourly;
  delete old.previous.hourly;
  const model = D.buildModel(old, day0 + DAY);
  assert.equal(model.step, "day");
  assert.equal(model.degraded, true);
  assert.equal(model.uses[0], 7); // el uso real se ve, no un cero
  // Con serie por horas disponible, nada cambia.
  const modern = base();
  const ok = D.buildModel(modern, day0 + DAY);
  assert.equal(ok.step, "hour");
  assert.equal(ok.degraded, false);
  // Una ventana larga nunca es «degradada»: ya era por días.
  const long = base();
  delete long.current.hourly;
  long.period.end = iso(day0 + 10 * DAY);
  long.period.compare_start = iso(day0 - 10 * DAY);
  assert.equal(D.buildModel(long).degraded, false);
});
console.log("todas las pruebas de derivación pasaron");
