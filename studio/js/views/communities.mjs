// Comunidades: instaladas, entradas, salidas y cuántas usan realmente a Purgito.
import { dataTable, legend, sparkline, timeChart } from "../charts.mjs";
import { emptyState, panel, stat } from "../components.mjs";
import { h } from "../dom.mjs";
import { fmtDateTime, fmtDay, fmtInt, fmtPct } from "../format.mjs";
import { COLORS } from "./overview.mjs";

const sum = (list) => list.reduce((a, b) => a + b, 0);

export function communities({ data, model }) {
  const cur = data.current;
  const root = h("div", { class: "stack" });
  const inv = model.inventory;
  const latest = data.latest_inventory;
  const entries = sum(model.entries);
  const exits = sum(model.exits);
  const rejoins = sum(model.rejoins);
  const observed = cur.observed_communities;

  root.append(
    h("div", { class: "kpis kpis-5" },
      stat({ label: "Servidores instalados", value: fmtInt(latest?.installed), note: latest ? `Inventario del ${fmtDay(latest.observed_at)}` : "Sin inventario", trend: inv.length > 1 ? sparkline(inv.map((i) => i.installed), { label: "Servidores instalados por día" }) : null }),
      stat({ label: "Entradas", value: fmtInt(entries), note: "Eventos de ingreso observados" }),
      stat({ label: "Salidas", value: fmtInt(exits), note: "Eventos de salida observados" }),
      stat({ label: "Reingresos", value: fmtInt(rejoins), note: "Servidores que ya habían estado" }),
      stat({ label: "Activas / observadas", value: observed ? fmtPct((100 * cur.summary.active) / observed, 0) : "—", note: observed ? `${fmtInt(cur.summary.active)} de ${fmtInt(observed)}` : "Sin inventario del período" }),
    ),
    h("p", { class: "note" }, "Instalar no es utilizar. El primer inventario es una línea base: no cuenta como instalaciones nuevas, y una diferencia entre inventarios no se convierte en entradas ni salidas."),
  );

  const invBody =
    inv.length > 1
      ? timeChart({ times: inv.map((i) => i.t), step: "day", series: [{ key: "installed", name: "Servidores instalados", values: inv.map((i) => i.installed), color: COLORS.series1, area: false }], annotations: model.annotations, zero: false, label: "Servidores instalados por día" })
      : emptyState({
          compact: true,
          title: inv.length ? "Un solo inventario por ahora" : "Sin inventarios en este período",
          text: inv.length ? `Hay ${fmtInt(inv[0].installed)} servidores el ${fmtDay(inv[0].t)}. La curva aparece con el segundo día de inventario: no se interpola entre días sin medir.` : "El inventario se guarda una vez por día en que el bot está conectado.",
        });
  const moveSeries = [
    { key: "entries", name: "Entradas", values: model.entries, color: "var(--series-1)" },
    { key: "rejoins", name: "Reingresos", values: model.rejoins, color: "var(--series-3)" },
    { key: "exits", name: "Salidas", values: model.exits, color: "var(--series-2)", side: -1 },
  ];
  const anyMove = entries + exits + rejoins > 0;
  root.append(
    h("div", { class: "grid grid-even" },
      panel({
        title: "Servidores instalados",
        subtitle: "Un punto por día con inventario · eje sin cero",
        body: invBody,
        table: inv.length ? dataTable(["Día (UTC)", "Instalados", "Observado"], inv.map((i) => [fmtDay(i.t), fmtInt(i.installed), fmtDateTime(i.observed_at)]), { caption: "Inventarios diarios" }) : null,
      }),
      panel({
        title: "Entradas y salidas",
        subtitle: "Eventos reales por día · las salidas van bajo el cero",
        legend: anyMove ? legend(moveSeries.map((i) => ({ name: i.name, color: i.color, kind: "box" }))) : null,
        body: anyMove ? timeChart({ times: model.dayTimes, step: "day", kind: "columns", window: [model.start, model.end], series: moveSeries, annotations: model.annotations, label: "Entradas, reingresos y salidas por día" }) : emptyState({ compact: true, title: "Sin movimientos observados", text: "No hubo ingresos ni salidas registrados mientras Studio medía. Un apagado no genera salidas inventadas." }),
        table: anyMove ? dataTable(["Día (UTC)", "Entradas", "Reingresos", "Salidas"], model.dayTimes.map((t, i) => [fmtDay(t), fmtInt(model.entries[i]), fmtInt(model.rejoins[i]), fmtInt(model.exits[i])]), { caption: "Movimientos diarios" }) : null,
      }),
    ),
  );
  return root;
}
