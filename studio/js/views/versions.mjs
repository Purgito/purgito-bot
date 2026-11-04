// Versiones: uso y calidad por versión del bot. Descriptivo: no atribuye causas.
import { rankedBars } from "../charts.mjs";
import { badge, emptyState, panel } from "../components.mjs";
import { h } from "../dom.mjs";
import { fmtInt, fmtPct } from "../format.mjs";

export function versions({ data, nav }) {
  const cur = data.current;
  const root = h("div", { class: "stack" });
  const running = data.collector.version;
  const rows = [...cur.versions].sort((a, b) => b.uses - a.uses);
  root.append(h("p", { class: "note" }, "Una comparación entre versiones es descriptiva. Un cambio de uso no se atribuye a una actualización: los períodos, la cobertura y la actividad de las comunidades también cambian. Registra cada despliegue en Actualizaciones para poder leerlo en los gráficos."));
  if (!rows.length) {
    root.append(emptyState({ title: "Sin uso por versión todavía", text: `Cuando haya ejecuciones aparecerán agrupadas por versión. Ahora se está ejecutando ${running}.` }));
    return root;
  }
  const total = rows.reduce((a, r) => a + r.uses, 0);
  root.append(
    h("div", { class: "grid grid-wide" },
      h("section", { class: "panel" },
        h("header", { class: "panel-head" }, h("div", {}, h("h2", { class: "panel-title" }, "Versiones en el período"), h("p", { class: "panel-sub" }, "Una fila por versión que registró uso"))),
        h("div", { class: "table-wrap" }, h("table", { class: "table" }, h("caption", { class: "sr-only" }, "Uso y calidad por versión"),
          h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Versión"), ["Usos", "Comunidades activas", "Éxitos", "Fallos", "Tasa de fallo"].map((t) => h("th", { scope: "col", class: "num" }, t)))),
          h("tbody", {}, rows.map((r) => h("tr", {}, h("th", { scope: "row" }, h("code", {}, r.version), r.version === running ? badge("En ejecución", "good") : null), h("td", { class: "num" }, fmtInt(r.uses)), h("td", { class: "num" }, fmtInt(r.active)), h("td", { class: "num" }, fmtInt(r.successes)), h("td", { class: "num" }, fmtInt(r.errors)), h("td", { class: "num" }, fmtPct(r.error_pct)))))))),
      panel({
        title: "Reparto del uso",
        subtitle: "Ejecuciones y entregas por versión",
        body: h("div", {}, rankedBars(rows.slice(0, 8).map((r) => ({ label: r.version, value: r.uses, text: fmtPct((100 * r.uses) / total, 0) }))), h("button", { type: "button", class: "btn btn-link", onclick: () => nav("updates") }, "Ver actualizaciones registradas")),
      }),
    ),
  );
  return root;
}
