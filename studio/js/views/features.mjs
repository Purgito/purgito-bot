// Funciones: qué se usa, cuánto se adopta y qué cobertura de instrumentación tiene cada una.
import { badge, emptyState, deltaChip, panel } from "../components.mjs";
import { h } from "../dom.mjs";
import { fmtInt, fmtNum, fmtPct } from "../format.mjs";
import { rankedBars } from "../charts.mjs";

const COVERAGE = {
  commands_and_deliveries: ["Comandos y entregas", "Se miden los comandos registrados y las entregas automáticas."],
  deliveries: ["Entregas", "Solo se miden las entregas, no hay comandos registrados."],
  commands: ["Comandos", "Se miden los comandos registrados."],
  explicit_events: ["Eventos explícitos", "Sin comandos ni entregas: solo cuenta lo que se registre a mano."],
  not_instrumented: ["Sin instrumentar", "No hay adaptador ni comandos: no se mide, y eso no es lo mismo que cero uso."],
};
const SOURCE = { prefix: "Prefijo", slash: "Slash", mention: "Mención", trigger: "Trigger", spontaneous: "Espontáneo", background: "Aviso", delivery: "Entrega" };

const sorting = { key: "uses", dir: -1 };
let commandLimit = 25;
let commandFilter = "";

function sortable(label, key, rerender, numeric = true) {
  const on = sorting.key === key;
  return h("th", { scope: "col", class: numeric ? "num" : "", "aria-sort": on ? (sorting.dir > 0 ? "ascending" : "descending") : "none" },
    h("button", { type: "button", class: "sort", onclick: () => { sorting.dir = on ? -sorting.dir : -1; sorting.key = key; rerender(); } }, label, h("span", { "aria-hidden": "true" }, on ? (sorting.dir > 0 ? " ↑" : " ↓") : "")));
}

export function features({ data, model, rerender }) {
  const cur = data.current;
  const partial = cur.coverage.status !== "complete";
  const root = h("div", { class: "stack" });
  const rows = [...cur.features];
  const val = (r) => (r.coverage === "not_instrumented" ? -1 : r[sorting.key] ?? -1);
  rows.sort((a, b) => (sorting.key === "label" ? a.label.localeCompare(b.label, "es") * sorting.dir : (val(a) - val(b)) * sorting.dir));

  const used = rows.filter((r) => r.uses);
  root.append(
    h("p", { class: "note" }, "Adopción = comunidades que usaron la función con éxito ÷ comunidades observadas en el período. No distingue permisos ni Premium: una función que una comunidad no puede usar cuenta como no adoptada."),
    used.length
      ? panel({
          title: "Uso por función",
          subtitle: "Ejecuciones y entregas en el período",
          body: rankedBars(used.sort((a, b) => b.uses - a.uses).slice(0, 10).map((f) => ({ label: f.label, hint: `${fmtInt(f.served)} ${f.served === 1 ? "comunidad" : "comunidades"}`, value: f.uses }))),
        })
      : emptyState({ title: "Todavía no hay uso de funciones", text: model.measuring ? "Cuando haya ejecuciones o entregas, aparecerán ordenadas aquí. Las funciones sin adaptador se muestran abajo como «Sin instrumentar»." : "Studio todavía no ha medido nada." }),
  );

  const table = h("table", { class: "table" }, h("caption", { class: "sr-only" }, "Funciones, uso y adopción"),
    h("thead", {}, h("tr", {}, sortable("Función", "label", rerender, false), h("th", { scope: "col" }, "Cobertura de medición"), sortable("Usos", "uses", rerender), sortable("Comunidades", "served", rerender), sortable("Adopción", "adoption_pct", rerender), h("th", { scope: "col", class: "num" }, "Cambio"), sortable("Fallos", "errors", rerender))),
    h("tbody", {}, rows.map((r) => {
      const [name, why] = COVERAGE[r.coverage] || ["—", ""];
      const off = r.coverage === "not_instrumented";
      const zeroText = partial ? "0 observados" : "0";
      const bar = r.adoption_pct == null ? null : h("span", { class: "mini-track" }, h("span", { class: "mini-fill" }));
      if (bar) bar.firstChild.style.setProperty("--w", `${Math.min(100, r.adoption_pct)}%`);
      const change = r.adoption_change_pp;
      return h("tr", { class: off ? "is-off" : "" },
        h("th", { scope: "row" }, r.label),
        h("td", {}, badge(name, off ? "muted" : "neutral", why)),
        h("td", { class: "num" }, off ? "—" : r.uses ? fmtInt(r.uses) : zeroText),
        h("td", { class: "num" }, off ? "—" : fmtInt(r.served)),
        h("td", { class: "num" }, r.adoption_pct == null ? "—" : h("span", { class: "adoption" }, bar, fmtPct(r.adoption_pct, r.adoption_pct % 1 ? 1 : 0))),
        h("td", { class: "num" }, change == null ? "—" : deltaChip({ kind: "full", tone: "neutral", text: `${change > 0 ? "▲" : change < 0 ? "▼" : "="} ${fmtNum(Math.abs(change), 1)} pp`, title: "Puntos porcentuales de adopción frente al período anterior", spoken: `${change > 0 ? "Sube" : "Baja"} ${fmtNum(Math.abs(change), 1)} puntos de adopción` })),
        h("td", { class: "num" }, off ? "—" : fmtInt(r.errors)));
    })));
  root.append(h("section", { class: "panel" }, h("header", { class: "panel-head" }, h("div", {}, h("h2", { class: "panel-title" }, "Todas las funciones"), h("p", { class: "panel-sub" }, "«Sin instrumentar» significa que no se mide, no que no se use"))), h("div", { class: "table-wrap" }, table)));

  const commands = cur.commands.filter((c) => c.command.toLowerCase().includes(commandFilter.toLowerCase()));
  const shown = commands.slice(0, commandLimit);
  const search = h("input", { type: "search", class: "input", placeholder: "Filtrar comandos", "aria-label": "Filtrar comandos", value: commandFilter, oninput: (e) => { commandFilter = e.target.value; commandLimit = 25; rerender({ keepFocus: "cmd-filter" }); }, id: "cmd-filter" });
  root.append(
    h("section", { class: "panel" },
      h("header", { class: "panel-head" }, h("div", {}, h("h2", { class: "panel-title" }, "Comandos"), h("p", { class: "panel-sub" }, "Solo comandos registrados; nunca sus argumentos")), search),
      cur.commands.length
        ? h("div", {}, h("div", { class: "table-wrap" }, h("table", { class: "table" }, h("caption", { class: "sr-only" }, "Uso por comando"),
            h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Comando"), h("th", { scope: "col" }, "Entrada"), ["Intentos", "Comunidades", "Fallos", "Tasa de fallo"].map((t) => h("th", { scope: "col", class: "num" }, t)))),
            h("tbody", {}, shown.map((c) => h("tr", {}, h("th", { scope: "row" }, h("code", {}, c.command)), h("td", {}, SOURCE[c.source] || c.source), h("td", { class: "num" }, fmtInt(c.uses)), h("td", { class: "num" }, fmtInt(c.served)), h("td", { class: "num" }, fmtInt(c.errors)), h("td", { class: "num" }, fmtPct(c.error_pct))))))),
          shown.length < commands.length ? h("div", { class: "more" }, h("button", { type: "button", class: "btn btn-link", onclick: () => { commandLimit += 50; rerender(); } }, `Mostrar más (${fmtInt(commands.length - shown.length)})`)) : null,
          !commands.length ? h("p", { class: "note pad" }, "Ningún comando coincide con el filtro.") : null)
        : h("div", { class: "pad" }, emptyState({ compact: true, title: "Sin comandos ejecutados", text: "Aparecerán aquí cuando alguien use un comando registrado." }))),
  );
  return root;
}
