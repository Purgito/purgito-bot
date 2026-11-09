// Retención: cuántas comunidades de cada cohorte siguen activas o instaladas el día exacto D1, D7 y D28.
// Las reglas (día UTC exacto, cohortes maduras, cobertura continua) las decide el backend: aquí solo se
// muestran. Lo inmaduro es una fecha futura, nunca un cero.
import { emptyNote, help, milestoneTrack, sectionHead, segmented } from "../components.mjs";
import { horizonState, milestones, retentionSummary } from "../derive.mjs";
import { h } from "../dom.mjs";
import { fmtDay, fmtInt, fmtRate } from "../format.mjs";

const ui = { kind: "activity", metric: "active" };

function horizon(x, metric, firstPending) {
  const gauge = h("span", { class: "hz-gauge", "aria-hidden": "true" }, h("span", {}));
  if (x.value != null) gauge.firstChild.style.setProperty("--w", `${Math.min(100, x.value)}%`);
  return h("div", { class: `hz${x.value == null ? " hz-empty" : ""}` },
    h("p", { class: "hz-name" }, `D${x.days}`),
    h("p", { class: "hz-value" }, x.value == null ? "—" : fmtRate(x.value, 1)),
    gauge,
    h("p", { class: "hz-note" }, x.n
      ? `de ${fmtInt(x.weight)} comunidades en ${fmtInt(x.n)} ${x.n === 1 ? "cohorte madura" : "cohortes maduras"}${x.baseline ? ", con línea base" : ""}`
      : firstPending ? `primera lectura el ${fmtDay(firstPending)}` : "sin cohortes maduras en el período"));
}

export function retention({ data, model, rerender }) {
  const root = h("div", { class: "page page-retention" });
  const rows = data.retention.filter((r) => r.kind === ui.kind);
  const metricKey = ui.metric === "active" ? "active_pct" : "installed_pct";

  root.append(h("div", { class: "toolbar" },
    segmented("ret-kind", [["activity", "Primera actividad observada"], ["installation", "Entradas observadas"]], ui.kind, (v) => { ui.kind = v; rerender(); }, "Tipo de cohorte"),
    segmented("ret-metric", [["active", "Siguen activas"], ["installed", "Siguen instaladas"]], ui.metric, (v) => { ui.metric = v; rerender(); }, "Métrica"),
    help(ui.kind === "activity"
      ? "«Primera actividad observada» no es la fecha de instalación: es el primer día con uso dentro de los datos retenidos. La línea base agrupa lo que ya existía cuando empezó la medición; no son servidores nuevos."
      : "Cohortes formadas por eventos reales de ingreso del bot. Es la única forma de saber cuándo se incorporó un servidor.", { label: "Qué es este tipo de cohorte" })));

  const summary = retentionSummary(rows, metricKey);
  const pendingAt = (days) => {
    const dates = rows.map((r) => horizonState(r.day, days, model.nowMs)).filter((s) => s.pending).map((s) => s.at);
    return dates.length ? Math.min(...dates) : null;
  };
  root.append(h("section", { class: "horizons", "aria-labelledby": "hz-t" },
    h("h2", { class: "sr-only", id: "hz-t" }, "Retención media por horizonte"),
    summary.map((x) => horizon(x, ui.metric, pendingAt(x.days))),
    h("p", { class: "hz-foot" }, "Media ponderada por tamaño de cohorte, solo con cohortes maduras.", help(data.definitions?.retention || ""))));

  const anyMature = summary.some((x) => x.n);
  if (!anyMature) {
    const mile = milestones(model.coverageStart, model.nowMs, 7).filter((m) => ["d1", "d7", "d28"].includes(m.key));
    root.append(h("section", { class: "upcoming", "aria-labelledby": "rm-t" },
      sectionHead(rows.length ? "Todavía no hay cohortes maduras" : ui.kind === "installation" ? "Sin entradas observadas en este período" : "Sin cohortes en este período", { id: "rm-t", level: 2 }),
      h("p", { class: "empty-text" }, model.measuring ? "Una cohorte necesita que pase el día de retorno completo, con cobertura continua e inventario. Hasta entonces se muestra «—» con la fecha de la primera lectura: no se rellena ni se estima." : "Studio todavía no ha medido nada."),
      // Sin ninguna cohorte, los horizontes no tienen fecha: la pista de hitos dice cuándo llegarán.
      !rows.length && model.coverageStart != null ? milestoneTrack(mile, model.coverageStart, model.nowMs) : null));
  }

  const since = data.observed_since ? Date.parse(data.observed_since) : null;
  if (ui.kind === "activity" && since != null && since < model.start)
    root.append(h("p", { class: "context-note" }, `El primer día medido (${fmtDay(since)}) forma la línea base y queda fuera de este período. Amplía el período para verla.`));

  if (!rows.length) return root;
  const maxSize = Math.max(...rows.map((r) => r.size));
  const head = h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Cohorte (UTC)"), h("th", { scope: "col", class: "num" }, "Comunidades"), h("th", { scope: "col" }, "Origen"), ["D1", "D7", "D28"].map((t) => h("th", { scope: "col", class: "center" }, t))));
  const body = h("tbody", {}, [...rows].reverse().map((r) => {
    const origin = r.kind === "installation" ? h("span", { class: "badge badge-good" }, "Entrada verificada")
      : r.baseline ? h("span", { class: "badge badge-neutral", title: "Existían antes de la medición o antes del límite de retención. No son servidores nuevos." }, "Línea base")
      : h("span", { class: "badge badge-quiet", title: "Solo cuenta como incorporación el evento real de ingreso." }, `${fmtInt(r.joined_observed)} de ${fmtInt(r.size)} con entrada`);
    const size = h("span", { class: "size-bar", "aria-hidden": "true" }, h("span", {}));
    size.firstChild.style.setProperty("--w", `${(100 * r.size) / maxSize}%`);
    return h("tr", {}, h("th", { scope: "row" }, fmtDay(`${r.day}T00:00:00Z`)), h("td", { class: "num cell-size" }, size, fmtInt(r.size)), h("td", {}, origin),
      r.horizons.map((hz) => {
        if (!hz.eligible || hz[metricKey] == null) {
          const st = horizonState(r.day, hz.days, model.nowMs);
          return h("td", { class: `heat-na${st.pending ? " is-pending" : ""}`, title: hz.reason || "Sin datos" }, h("span", { class: "sr-only" }, "Sin datos: "), st.pending ? `el ${fmtDay(st.at)}` : "sin cobertura");
        }
        const v = hz[metricKey];
        const cell = h("td", { class: "heat" }, fmtRate(v, v % 1 ? 1 : 0));
        cell.style.setProperty("--v", String(Math.min(100, v)));
        return cell;
      }));
  }));
  root.append(h("section", { class: "matrix", "aria-labelledby": "mx-t" },
    sectionHead(ui.kind === "activity" ? "Cohortes por primera actividad" : "Cohortes por entrada", { id: "mx-t", sub: ui.metric === "active" ? "porcentaje de la cohorte con uso exitoso el día exacto D+N" : "porcentaje de la cohorte presente en el inventario del día D+N" }),
    h("div", { class: "table-wrap" }, h("table", { class: "table heatmap" }, h("caption", { class: "sr-only" }, "Retención por cohorte"), head, body)),
    h("p", { class: "heat-key" }, h("span", { class: "heat-ramp", "aria-hidden": "true" }), "0 % – 100 %", h("span", { class: "heat-key-na", "aria-hidden": "true" }), "aún no madura (fecha en que podrá leerse)")));
  return root;
}
