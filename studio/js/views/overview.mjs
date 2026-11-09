// Resumen: el estado de Purgito de un vistazo. Una protagonista (comunidades que usaron Purgito), cuatro
// cifras de apoyo, el pulso de actividad y dos puertas: dónde está el uso y cómo de bien funciona.
import { legend, miniColumns, seriesTable, shareStrip, swatch, timeChart } from "../charts.mjs";
import { chartOrTable, deltaChip, emptyNote, figure, goTo, milestoneTrack, sectionHead, segmented } from "../components.mjs";
import { deltaInfo, featureGroups, milestones, qualitySignal, rateDelta, statusSentence } from "../derive.mjs";
import { h } from "../dom.mjs";
import { fmtDay, fmtInt, fmtMs, fmtRate, fmtShare } from "../format.mjs";
import { C, categorical, OTHER } from "../palette.mjs";
import { focusFeature } from "./features.mjs";

const ui = { metric: "uses" };

export function usageSeries(model, comparison, data, metric = "uses") {
  const name = metric === "uses" ? "Ejecuciones y entregas" : "Comunidades activas";
  const cur = metric === "uses" ? model.uses : model.active;
  const prev = metric === "uses" ? model.prevUses : model.prevActive;
  const list = [{ key: metric, name, values: cur, color: C.current, area: true }];
  const prevHasData = data.previous.coverage.ratio > 0 && prev.some((v) => v);
  if (comparison.status !== "not_comparable" && prevHasData) list.push({ key: "prev", name: "Período anterior", values: prev, color: C.prev, muted: true });
  return list;
}

function hero(data, model) {
  const cur = data.current;
  const s = cur.summary;
  const partial = cur.coverage.status !== "complete";
  const observed = cur.observed_communities;
  const delta = deltaInfo(data.delta.active, true);
  return h("section", { class: "hero", "aria-labelledby": "hero-t" },
    h("h2", { class: "sr-only", id: "hero-t" }, "Estado general"),
    h("p", { class: "hero-statement" },
      h("span", { class: "hero-figure" }, fmtInt(s.active)),
      h("span", { class: "hero-words" }, s.active === 1 ? "comunidad usó Purgito" : "comunidades usaron Purgito",
        h("span", { class: "hero-of" }, observed ? `de las ${fmtInt(observed)} observadas en el período (${fmtShare(s.active, observed, 0)})` : "sin inventario del período para calcular la proporción"))),
    h("div", { class: "hero-meta" }, deltaChip(delta), partial ? h("span", { class: "minimum" }, "mínimo: parte del período sin medir") : null),
    h("p", { class: "sr-only" }, statusSentence(data, model)));
}

function supporting(data, model) {
  const s = data.current.summary;
  const inv = data.latest_inventory;
  const attempts = s.successes + s.errors;
  const partial = data.current.coverage.status !== "complete";
  return h("div", { class: "figures figures-4" },
    figure({ label: "Instalado en", value: fmtInt(inv?.installed), unit: inv ? (inv.installed === 1 ? "servidor" : "servidores") : null, note: inv ? `Inventario del ${fmtDay(inv.observed_at)}` : "Sin inventario todavía", info: data.definitions?.installed }),
    figure({ label: "Ejecuciones y entregas", value: fmtInt(s.uses), delta: deltaInfo(data.delta.uses, null), minimum: partial }),
    figure({ label: "Tasa de fallo", value: attempts ? fmtRate(s.error_pct, 2) : "—", delta: rateDelta(s.error_pct, data.previous.summary.error_pct, data.comparison, false), note: attempts ? `${fmtInt(s.errors)} de ${fmtInt(attempts)} intentos` : "Sin intentos registrados", info: data.definitions?.errors }),
    figure({ label: "Latencia media", value: fmtMs(s.mean_ms), note: s.p95_ms_upper_bound ? `El 95 % por debajo de ${fmtMs(s.p95_ms_upper_bound)}` : s.p95_over_30000_ms ? "El 5 % más lento supera 30 s" : "Sin muestras de latencia", info: data.definitions?.latency }));
}

function pulse(data, model, rerender) {
  const unit = model.step === "hour" ? "por hora" : "por día";
  const series = usageSeries(model, data.comparison, data, ui.metric);
  const name = ui.metric === "uses" ? "Ejecuciones y entregas" : "Comunidades activas";
  const toggle = segmented("pulse-metric", [["uses", "Usos"], ["active", "Comunidades"]], ui.metric, (v) => { ui.metric = v; rerender(); }, "Métrica del gráfico", { small: true });
  if (!model.hasUsage)
    return h("section", { class: "pulse", "aria-labelledby": "pulse-t" }, sectionHead("Actividad", { id: "pulse-t" }),
      emptyNote({ title: "Sin uso registrado en lo medido", text: data.current.coverage.status === "complete" ? "Nadie ha ejecutado comandos ni recibido entregas en este período." : "Con la cobertura incompleta no se puede afirmar que no hubo uso." }));
  const chart = timeChart({ times: model.times, step: model.step, series, gaps: model.gaps, window: [model.start, model.end], annotations: model.annotations, label: `${name} ${unit}`, height: 280, unit: ui.metric === "uses" ? "usos" : "comunidades" });
  const { button, body } = chartOrTable(chart, seriesTable(model.times, model.step, series));
  return h("section", { class: "pulse", "aria-labelledby": "pulse-t" },
    sectionHead("Actividad", { id: "pulse-t", sub: `${name.toLowerCase()} ${unit}, UTC`, actions: [toggle, button] }),
    series.length > 1 ? legend(series.map((i) => ({ name: i.name, color: i.color, kind: i.muted ? "dash" : "line" }))) : null,
    body);
}

function where(data, nav) {
  const { used, total } = featureGroups(data.current.features);
  if (!used.length)
    return h("section", { class: "where", "aria-labelledby": "where-t" }, sectionHead("Dónde está el uso", { id: "where-t" }),
      emptyNote({ title: "Sin funciones usadas todavía", text: "Aparecerán en cuanto haya ejecuciones o entregas." }));
  const top = used.slice(0, 5);
  const rest = used.slice(5);
  const restUses = rest.reduce((a, f) => a + f.uses, 0);
  const color = categorical(top.map((f) => f.feature));
  const parts = [...top.map((f) => ({ key: f.feature, label: f.label, value: f.uses, color: color(f.feature) })), ...(restUses ? [{ key: "other", label: `Otras ${rest.length}`, value: restUses, color: OTHER }] : [])];
  const lead = top.length > 1 ? `${top[0].label} y ${top[1].label} reúnen el ${fmtShare(top[0].uses + top[1].uses, total, 0)} del uso` : `${top[0].label} reúne todo el uso`;
  return h("section", { class: "where", "aria-labelledby": "where-t" },
    sectionHead("Dónde está el uso", { id: "where-t", sub: lead }),
    shareStrip(parts, { ariaLabel: `Reparto del uso: ${parts.map((p) => `${p.label} ${fmtShare(p.value, total)}`).join(", ")}` }),
    h("ol", { class: "share-list" }, parts.map((p) => {
      const f = used.find((x) => x.feature === p.key);
      return h("li", {},
        h("button", { type: "button", class: "share-row", onclick: () => { if (p.key !== "other") focusFeature(p.key); nav("features"); } },
          swatch(p.color, "box"),
          h("span", { class: "share-name" }, p.label),
          h("span", { class: "share-num" }, fmtInt(p.value)),
          h("span", { class: "share-pct" }, fmtShare(p.value, total)),
          h("span", { class: "share-reach" }, f ? `${fmtInt(f.served)} ${f.served === 1 ? "comunidad" : "comunidades"}` : "")));
    })),
    goTo("Ver todas las funciones", () => nav("features")));
}

function signal(data, model, nav) {
  const s = data.current.summary;
  const q = qualitySignal(s);
  const unit = model.step === "hour" ? "por hora" : "por día";
  return h("section", { class: `signal signal-${q.tone}`, "aria-labelledby": "signal-t" },
    sectionHead("Calidad", { id: "signal-t" }),
    h("p", { class: "signal-line" }, h("span", { class: "sev", "aria-hidden": "true" }), q.text),
    q.attempts ? h("div", { class: "signal-body" },
      miniColumns(model.errors, { color: C.error, label: `Fallos ${unit}: ${fmtInt(s.errors)} en total` }),
      h("dl", { class: "facts facts-compact" },
        h("div", {}, h("dt", {}, "Fallos"), h("dd", {}, `${fmtInt(s.errors)} de ${fmtInt(q.attempts)}`)),
        h("div", {}, h("dt", {}, "Rechazos de Discord"), h("dd", {}, fmtInt(s.refused))),
        h("div", {}, h("dt", {}, "Validaciones previas"), h("dd", {}, fmtInt(s.rejected))))) : null,
    goTo("Abrir el diagnóstico", () => nav("reliability")));
}

export function overview({ data, model, nav, rerender }) {
  const root = h("div", { class: "page page-overview" });
  if (!model.measuring) {
    root.append(emptyNote({
      tone: "first",
      title: "Studio todavía no ha medido nada",
      text: "La recopilación empieza cuando el bot se conecta a Discord con Studio activado. Con el primer volcado, esta portada se llena sola.",
    }));
    return root;
  }
  if (!model.hasUsage && model.nowMs - model.coverageStart < 2 * 3_600_000) {
    root.append(h("p", { class: "lead" }, statusSentence(data, model)));
  }
  root.append(h("div", { class: "overview-top" }, hero(data, model), supporting(data, model)));
  root.append(pulse(data, model, rerender));
  root.append(h("div", { class: "overview-pair" }, where(data, nav), signal(data, model, nav)));
  const days = Math.max(1, Math.round((model.end - model.start) / 86_400_000));
  const mile = milestones(model.coverageStart, model.nowMs, days).filter((m) => !m.done);
  if (mile.length)
    root.append(h("section", { class: "upcoming", "aria-labelledby": "up-t" }, sectionHead("Cuándo habrá más datos", { id: "up-t", sub: `se mide desde el ${fmtDay(model.coverageStart)}` }), milestoneTrack(mile, model.coverageStart, model.nowMs)));
  return root;
}
