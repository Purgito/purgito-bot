// Comunidades: cuántos servidores tienen Purgito, cuántos lo usan y cómo se mueve la población. Instalar no
// es usar; el primer inventario es una línea base; un apagado no genera salidas.
import { dataTable, legend, timeChart, unitGrid } from "../charts.mjs";
import { chartOrTable, emptyNote, sectionHead } from "../components.mjs";
import { movementTotals } from "../derive.mjs";
import { h } from "../dom.mjs";
import { fmtDateTime, fmtDay, fmtInt, fmtShare } from "../format.mjs";
import { C } from "../palette.mjs";

function population(data, model) {
  const latest = data.latest_inventory;
  const inv = model.inventory;
  let verdict = null;
  if (inv.length >= 2) {
    const diff = inv.at(-1).installed - inv[0].installed;
    verdict = diff === 0
      ? `Igual que el ${fmtDay(inv[0].t)}, el primer inventario del período`
      : `${diff > 0 ? "+" : "−"}${fmtInt(Math.abs(diff))} desde el ${fmtDay(inv[0].t)}, el primer inventario del período`;
  }
  return h("section", { class: "pop-hero", "aria-labelledby": "ph-t" },
    h("h2", { class: "sr-only", id: "ph-t" }, "Población"),
    h("p", { class: "hero-statement" },
      h("span", { class: "hero-figure" }, fmtInt(latest?.installed)),
      h("span", { class: "hero-words" }, latest?.installed === 1 ? "servidor tiene Purgito" : "servidores tienen Purgito",
        h("span", { class: "hero-of" }, latest ? `según el inventario del ${fmtDay(latest.observed_at)}` : "todavía no hay inventario"))),
    verdict ? h("p", { class: "verdict" }, verdict) : inv.length === 1 ? h("p", { class: "verdict verdict-quiet" }, "Línea base: con un solo inventario en el período todavía no hay tendencia que mostrar.") : null);
}

function activeShare(data) {
  const cur = data.current;
  const observed = cur.observed_communities;
  const active = cur.summary.active;
  return h("section", { class: "use-share", "aria-labelledby": "us-t" },
    sectionHead("Instaladas frente a activas", { id: "us-t", info: data.definitions?.active }),
    observed
      ? [h("p", { class: "use-line" }, h("strong", {}, fmtInt(active)), ` de ${fmtInt(observed)} comunidades observadas usaron alguna función (${fmtShare(active, observed, 0)}).`),
        observed <= 600 ? unitGrid(observed, Math.min(active, observed), { label: `${fmtInt(active)} activas de ${fmtInt(observed)} observadas` }) : null,
        h("p", { class: "units-key" }, h("span", { class: "unit-key unit-key-on", "aria-hidden": "true" }), "activa", h("span", { class: "unit-key", "aria-hidden": "true" }), "instalada sin uso observado")]
      : emptyNote({ title: "Sin inventario en el período", text: "La proporción necesita al menos un inventario: se guarda una vez al día con el bot conectado." }));
}

function installedChart(data, model) {
  const inv = model.inventory;
  let body;
  let table = null;
  if (inv.length > 1) {
    body = timeChart({ times: inv.map((i) => i.t), step: "day", series: [{ key: "installed", name: "Servidores instalados", values: inv.map((i) => i.installed), color: C.current }], annotations: model.annotations, zero: false, label: "Servidores instalados por día", height: 210 });
    table = dataTable(["Día (UTC)", "Instalados", "Observado"], inv.map((i) => [fmtDay(i.t), fmtInt(i.installed), fmtDateTime(i.observed_at)]), { caption: "Inventarios diarios" });
  } else {
    body = emptyNote({
      title: inv.length ? "Un solo inventario por ahora" : "Sin inventarios en este período",
      text: inv.length ? "La curva aparece con el segundo día de inventario. Entre días sin medir no se interpola." : "El inventario se guarda una vez por día en que el bot está conectado.",
    });
  }
  const { button, body: view } = chartOrTable(body, table);
  return h("section", { class: "installed", "aria-labelledby": "in-t" },
    sectionHead("Servidores instalados", { id: "in-t", sub: inv.length > 1 ? "un punto por inventario diario, eje sin cero" : null, info: data.definitions?.installed, actions: [button] }),
    view);
}

function movements(data, model) {
  const t = movementTotals(model);
  const series = [
    { key: "entries", name: "Entradas", values: model.entries, color: C.entries },
    { key: "rejoins", name: "Reingresos", values: model.rejoins, color: C.rejoins },
    { key: "exits", name: "Salidas", values: model.exits, color: C.exits, side: -1 },
  ];
  const ledger = h("dl", { class: "ledger" },
    h("div", {}, h("dt", {}, "Entradas"), h("dd", {}, fmtInt(t.entries))),
    h("div", {}, h("dt", {}, "Reingresos"), h("dd", {}, fmtInt(t.rejoins))),
    h("div", {}, h("dt", {}, "Salidas"), h("dd", {}, t.exits ? `−${fmtInt(t.exits)}` : "0")),
    h("div", { class: "ledger-net" }, h("dt", {}, "Neto observado"), h("dd", {}, `${t.net > 0 ? "+" : t.net < 0 ? "−" : ""}${fmtInt(Math.abs(t.net))}`)));
  if (!t.any)
    return h("section", { class: "moves", "aria-labelledby": "mv-t" }, sectionHead("Entradas y salidas", { id: "mv-t" }),
      emptyNote({ title: "Sin movimientos observados", text: "No hubo ingresos ni salidas registrados mientras Studio medía. Un apagado no genera salidas inventadas." }));
  const chart = timeChart({ times: model.dayTimes, step: "day", kind: "columns", window: [model.start, model.end], gaps: model.gaps, series, annotations: model.annotations, label: "Entradas, reingresos y salidas por día", height: 210, unit: "servidores" });
  const table = dataTable(["Día (UTC)", "Entradas", "Reingresos", "Salidas"], model.dayTimes.map((d, i) => [fmtDay(d), fmtInt(model.entries[i]), fmtInt(model.rejoins[i]), fmtInt(model.exits[i])]), { caption: "Movimientos diarios" });
  const { button, body } = chartOrTable(chart, table);
  return h("section", { class: "moves", "aria-labelledby": "mv-t" },
    sectionHead("Entradas y salidas", { id: "mv-t", sub: "eventos reales de ingreso y salida; las salidas van bajo el cero", info: "Solo cuentan eventos de Discord observados mientras Studio medía. Una diferencia entre inventarios no se convierte en entradas ni salidas, y un apagado no genera salidas.", actions: [button] }),
    h("div", { class: "moves-body" }, h("div", { class: "moves-chart" }, legend(series.map((i) => ({ name: i.name, color: i.color, kind: "box" }))), body), ledger));
}

export function communities({ data, model, filters }) {
  const root = h("div", { class: "page page-communities" });
  if (!model.measuring) {
    root.append(emptyNote({ tone: "first", title: "Studio todavía no ha medido nada", text: "El primer inventario se guarda cuando el bot se conecta con Studio activado." }));
    return root;
  }
  root.append(population(data, model));
  if (filters.feature || filters.result) root.append(h("p", { class: "context-note" }, "Instalaciones y movimientos no usan los filtros de función ni de resultado; la proporción de activas sí."));
  root.append(h("div", { class: "comm-grid" }, installedChart(data, model), activeShare(data)));
  root.append(movements(data, model));
  return root;
}

