// Retención: cuántas comunidades de cada cohorte siguen presentes o activas a D1, D7 y D28.
// Las reglas (día UTC exacto, cohortes maduras, cobertura continua) las decide el backend; aquí solo se muestran.
import { emptyState, milestoneList, stat } from "../components.mjs";
import { milestones } from "../derive.mjs";
import { h } from "../dom.mjs";
import { fmtDay, fmtInt, fmtPct } from "../format.mjs";

const ui = { kind: "activity", metric: "active" };

function radios(name, options, current, onChange, legend) {
  return h("fieldset", { class: "seg" }, h("legend", { class: "sr-only" }, legend),
    options.map(([value, text]) => h("label", {}, h("input", { type: "radio", name, value, checked: value === current ? true : null, onchange: () => onChange(value) }), h("span", {}, text))));
}

export function retention({ data, model, rerender }) {
  const root = h("div", { class: "stack" });
  const all = data.retention;
  const rows = all.filter((r) => r.kind === ui.kind);
  const metricKey = ui.metric === "active" ? "active_pct" : "installed_pct";

  root.append(
    h("div", { class: "toolbar" },
      radios("ret-kind", [["activity", "Primera actividad observada"], ["installation", "Entradas observadas"]], ui.kind, (v) => { ui.kind = v; rerender(); }, "Tipo de cohorte"),
      radios("ret-metric", [["active", "Siguen activas"], ["installed", "Siguen instaladas"]], ui.metric, (v) => { ui.metric = v; rerender(); }, "Métrica"),
    ),
    h("p", { class: "note" }, ui.kind === "activity"
      ? "«Primera actividad observada» no es la fecha de instalación: es el primer día con uso dentro de los datos retenidos. La línea base agrupa lo que ya existía cuando empezó la medición; no son servidores nuevos."
      : "Cohortes formadas por eventos reales de ingreso del bot. Es la única forma de saber cuándo se incorporó un servidor."),
  );

  const since = data.observed_since ? Date.parse(data.observed_since) : null;
  if (ui.kind === "activity" && since != null && since < model.start)
    root.append(h("p", { class: "note" }, `El primer día medido (${fmtDay(since)}) forma la línea base y queda fuera de este período. Amplía el período con «Personalizado» para verla.`));

  // Resumen ponderado por horizonte (solo cohortes maduras).
  const summary = [1, 7, 28].map((days) => {
    let weight = 0;
    let acc = 0;
    let n = 0;
    let baseline = false;
    for (const r of rows) {
      const hz = r.horizons.find((x) => x.days === days);
      if (hz?.eligible && hz[metricKey] != null) {
        weight += r.size;
        acc += hz[metricKey] * r.size;
        n += 1;
        baseline ||= r.baseline;
      }
    }
    return { days, value: weight ? acc / weight : null, n, weight, baseline };
  });

  const anyMature = summary.some((x) => x.n);
  if (!rows.length || !anyMature) {
    const mile = milestones(model.coverageStart, model.nowMs, 7).filter((m) => ["d1", "d7", "d28"].includes(m.key));
    root.append(
      emptyState({
        title: rows.length ? "Todavía no hay cohortes maduras" : ui.kind === "installation" ? "Sin entradas observadas en este período" : "Sin cohortes en este período",
        text: model.measuring
          ? "Una cohorte necesita que pase el día de retorno completo, con cobertura continua e inventario. Hasta entonces se muestra «—»: no se rellena ni se estima."
          : "Studio todavía no ha medido nada.",
        items: milestoneList(mile, model.nowMs),
      }),
    );
    if (!rows.length) return root;
  } else {
    root.append(
      h("div", { class: "kpis kpis-3" },
        summary.map((x) => stat({
          label: `D${x.days}`,
          value: x.value == null ? "—" : fmtPct(x.value, 1),
          note: x.n ? `${fmtInt(x.n)} ${x.n === 1 ? "cohorte madura" : "cohortes maduras"} · ${fmtInt(x.weight)} comunidades${x.baseline ? " · incluye línea base" : ""}` : "Aún sin cohortes maduras",
        })),
      ),
    );
  }

  const head = h("thead", {}, h("tr", {}, ["Cohorte (UTC)", "Comunidades", "Origen", "D1", "D7", "D28"].map((t, i) => h("th", { scope: "col", class: i === 1 ? "num" : i > 2 ? "center" : "" }, t))));
  const body = h("tbody", {}, rows.map((r) => {
    const origin = r.kind === "installation" ? h("span", { class: "badge badge-good" }, "Entrada verificada")
      : r.baseline ? h("span", { class: "badge badge-neutral", title: "Existían antes de la medición o antes del límite de retención. No son servidores nuevos." }, "Línea base")
      : h("span", { class: "badge badge-neutral", title: "Solo cuenta como incorporación el evento real de ingreso." }, `${fmtInt(r.joined_observed)} de ${fmtInt(r.size)} con entrada`);
    return h("tr", {}, h("th", { scope: "row" }, fmtDay(`${r.day}T00:00:00Z`)), h("td", { class: "num" }, fmtInt(r.size)), h("td", {}, origin),
      r.horizons.map((hz) => {
        if (!hz.eligible || hz[metricKey] == null)
          return h("td", { class: "heat-na num", title: hz.reason || "Sin datos" }, h("span", { class: "sr-only" }, "Sin datos: "), "—");
        const cell = h("td", { class: "heat num" }, fmtPct(hz[metricKey], hz[metricKey] % 1 ? 1 : 0));
        cell.style.setProperty("--v", String(Math.min(100, hz[metricKey])));
        return cell;
      }));
  }));
  if (rows.length)
    root.append(h("section", { class: "panel" },
      h("header", { class: "panel-head" }, h("div", {}, h("h2", { class: "panel-title" }, ui.kind === "activity" ? "Cohortes por primera actividad" : "Cohortes por entrada"), h("p", { class: "panel-sub" }, ui.metric === "active" ? "Porcentaje de la cohorte con uso exitoso el día exacto D+N" : "Porcentaje de la cohorte presente en el inventario del día D+N"))),
      h("div", { class: "table-wrap" }, h("table", { class: "table heatmap" }, h("caption", { class: "sr-only" }, "Retención por cohorte"), head, body))));
  return root;
}
