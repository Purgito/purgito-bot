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
t("rateDelta: por debajo de 0,05 pp no hay flecha ni «0 pp»", () => {
  const same = D.rateDelta(0.32, 0.29, { status: "comparable" });
  assert.equal(same.tone, "neutral");
  assert.equal(same.text, "= sin cambio");
  assert.doesNotMatch(same.spoken, /0 puntos/);
  assert.equal(D.rateDelta(0.5, 0.3, { status: "comparable" }).text, "▲ 0,2 pp");
});
t("qualitySignal: describe sin diagnosticar; dos fallos no son un incidente", () => {
  assert.equal(D.qualitySignal({ successes: 0, errors: 0 }).tone, "none");
  assert.equal(D.qualitySignal({ successes: 699, errors: 0, error_pct: 0 }).text, "Sin fallos en lo medido");
  const two = D.qualitySignal({ successes: 699, errors: 2, error_pct: 0.29 });
  assert.equal(two.tone, "calm");
  assert.equal(two.text, "Fallos por debajo del 1 %");
  const small = D.qualitySignal({ successes: 3, errors: 2, error_pct: 40 });
  assert.equal(small.tone, "calm");
  assert.match(small.text, /2 fallos en 5 intentos/);
  assert.equal(D.qualitySignal({ successes: 90, errors: 10, error_pct: 10 }).tone, "attention");
  assert.equal(D.qualitySignal({ successes: 970, errors: 30, error_pct: 3 }).tone, "watch");
});
t("p95Interval: intervalo del histograma, nunca una cifra exacta", () => {
  assert.deepEqual(D.p95Interval({ p95_ms_upper_bound: 2500 }), [1000, 2500]);
  assert.deepEqual(D.p95Interval({ p95_ms_upper_bound: 25 }), [0, 25]);
  assert.deepEqual(D.p95Interval({ p95_over_30000_ms: true }), [30000, null]);
  assert.equal(D.p95Interval({ p95_ms_upper_bound: null }), null);
});
t("featureGroups: usado, sin uso observado y sin instrumentar nunca se mezclan", () => {
  const g = D.featureGroups([
    { feature: "chat", uses: 10, coverage: "deliveries" },
    { feature: "gifs", uses: 30, coverage: "commands_and_deliveries" },
    { feature: "rss", uses: 0, coverage: "deliveries" },
    { feature: "privacy", uses: null, coverage: "not_instrumented" },
  ]);
  assert.deepEqual(g.used.map((f) => f.feature), ["gifs", "chat"]);
  assert.deepEqual(g.idle.map((f) => f.feature), ["rss"]);
  assert.deepEqual(g.blind.map((f) => f.feature), ["privacy"]);
  assert.equal(g.total, 40);
});
t("versionLanes: tramos por día de inventario, sin rellenar días sin inventario", () => {
  const inv = [0, 1, 2, 5, 6].map((i) => ({ t: day0 + i * DAY, version: i < 2 ? "aaaaaaa" : "bbbbbbb" }));
  const lanes = D.versionLanes(inv, [{ kind: "release", version: "bbbbbbb", t: day0 + 2 * DAY }]);
  assert.deepEqual(lanes.map((l) => l.version), ["aaaaaaa", "bbbbbbb"]);
  assert.equal(lanes[1].spans.length, 2);
  assert.equal(lanes[1].release.kind, "release");
});
t("horizonState y retentionSummary: lo inmaduro es una fecha, la media es ponderada", () => {
  const st = D.horizonState("2026-11-01", 7, day0 + 3 * DAY);
  assert.equal(st.pending, true);
  assert.equal(st.at, day0 + 8 * DAY);
  assert.equal(D.horizonState("2026-11-01", 1, day0 + 9 * DAY).pending, false);
  const rows = [
    { size: 10, horizons: [{ days: 1, eligible: true, active_pct: 50 }, { days: 7, eligible: false, active_pct: null }, { days: 28, eligible: false }] },
    { size: 30, horizons: [{ days: 1, eligible: true, active_pct: 70 }, { days: 7, eligible: false }, { days: 28, eligible: false }] },
  ];
  const s = D.retentionSummary(rows, "active_pct");
  assert.equal(s[0].value, 65);
  assert.equal(s[0].weight, 40);
  assert.equal(s[1].value, null);
});
t("commandFeature: el catálogo del bot asigna cada comando a su función", () => {
  const of = D.commandFeature([{ source: "slash", command: "gifs", feature: "gifs" }]);
  assert.equal(of({ source: "slash", command: "gifs" }), "gifs");
  assert.equal(of({ source: "prefix", command: "gifs" }), null);
});
console.log("todas las pruebas de derivación pasaron");
