// Versiones: qué versión se ejecuta, cuándo estuvo cada una y cómo se usó. Descriptivo: una coincidencia
// temporal no demuestra que una actualización cambiara el uso o la calidad.
import { swatch, versionTrack } from "../charts.mjs";
import { badge, emptyNote, goTo, help, icon, sectionHead } from "../components.mjs";
import { SMALL_SAMPLE, versionLanes } from "../derive.mjs";
import { h } from "../dom.mjs";
import { fmtDay, fmtInt, fmtRate, fmtShare, isCommit, shortVersion } from "../format.mjs";
import { CATEGORICAL, OTHER } from "../palette.mjs";

const REPO = "https://github.com/Purgito/purgito-bot/commit/";

export function versionLabel(v, { link = true } = {}) {
  const code = h("code", { class: "hash" }, shortVersion(v));
  if (!link || !isCommit(v)) return code;
  return h("a", { class: "hash-link", href: `${REPO}${encodeURIComponent(v)}`, target: "_blank", rel: "noopener noreferrer", title: `Abrir el commit ${v} en GitHub` }, code, icon("external", { size: 13 }), h("span", { class: "sr-only" }, " (abre GitHub en otra pestaña)"));
}

export function versions({ data, model, nav, setFilters, filters }) {
  const cur = data.current;
  const root = h("div", { class: "page page-versions" });
  const running = data.collector.version;
  const rows = [...cur.versions].sort((a, b) => b.uses - a.uses);
  const lanes = versionLanes(model.inventory, model.annotations);
  const order = [...new Set([...lanes.map((l) => l.version), ...rows.map((r) => r.version)])];
  // El cian es lo actual: solo la versión en ejecución lo lleva; las demás, colores categóricos.
  const others = order.filter((v) => v !== running);
  const colorMap = new Map([[running, "var(--accent)"], ...others.map((v, i) => [v, CATEGORICAL[i % CATEGORICAL.length] || OTHER])]);
  const color = (v) => colorMap.get(v) || OTHER;
  const runningLane = lanes.find((l) => l.version === running);
  const release = model.annotations.filter((a) => a.kind === "release" && a.version === running).at(-1);

  root.append(h("section", { class: "running-hero", "aria-labelledby": "rv-t" },
    h("h2", { class: "sr-only", id: "rv-t" }, "Versión en ejecución"),
    h("p", { class: "running-line" }, h("span", { class: "running-label" }, "En ejecución"), versionLabel(running)),
    h("p", { class: "running-meta" },
      release ? `«${release.title}», registrado el ${fmtDay(release.t)}` : runningLane ? `Presente en los inventarios desde el ${fmtDay(runningLane.first)}` : "Aún no aparece en ningún inventario del período",
      help("Las versiones son identificadores de Git del bot. La fecha de cada carril sale del inventario diario, así que es aproximada por día; la hora exacta de un despliegue se registra en Actualizaciones."))));

  if (!rows.length) {
    root.append(emptyNote({ title: "Sin uso por versión todavía", text: "Cuando haya ejecuciones aparecerán agrupadas por versión." }));
    return root;
  }

  if (lanes.length)
    root.append(h("section", { class: "lanes-sec", "aria-labelledby": "vl-t" },
      sectionHead("Cuándo estuvo cada versión", { id: "vl-t", sub: "presencia en el inventario diario; ◆ despliegue registrado" }),
      versionTrack(lanes, { start: model.start, end: model.end, colors: color, running, annotations: model.annotations.filter((a) => a.kind === "release"), label: `Versiones por día: ${lanes.map((l) => `${shortVersion(l.version)} del ${fmtDay(l.first)} al ${fmtDay(l.last)}`).join("; ")}` })));

  const total = rows.reduce((a, r) => a + r.uses, 0);
  const max = Math.max(...rows.map((r) => r.uses));
  root.append(h("section", { class: "vcompare", "aria-labelledby": "vc-t" },
    sectionHead(rows.length > 1 ? "Versiones en el período" : "Versiones en el período: solo una", { id: "vc-t", sub: rows.length > 1 ? "elige una para filtrar todo Studio por ella" : "con una sola versión no hay nada que comparar todavía", info: "La comparación es descriptiva. Los períodos de cada versión tienen distinta duración y cobertura, y la actividad de las comunidades también cambia: una diferencia no se atribuye a la actualización." }),
    h("div", { class: "table-wrap" }, h("table", { class: "table vtable" }, h("caption", { class: "sr-only" }, "Uso y calidad por versión"),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Versión"), h("th", { scope: "col", class: "num" }, "Usos"), h("th", { scope: "col", class: "num" }, "Cuota"), h("th", { scope: "col", class: "num" }, "Comunidades activas"), h("th", { scope: "col", class: "num" }, "Tasa de fallo"), h("th", { scope: "col" }, h("span", { class: "sr-only" }, "Filtrar")))),
      h("tbody", {}, rows.map((r) => {
        const attempts = r.successes + r.errors;
        const track = h("span", { class: "cell-bar", "aria-hidden": "true" }, h("span", {}));
        track.firstChild.style.setProperty("--w", `${(100 * r.uses) / max}%`);
        track.firstChild.style.setProperty("--c", color(r.version));
        const on = filters.version === r.version;
        return h("tr", { class: r.version === running ? "is-running" : "" },
          h("th", { scope: "row" }, h("span", { class: "vname" }, swatch(color(r.version), "box"), versionLabel(r.version), r.version === running ? badge("en ejecución", "good") : null)),
          h("td", { class: "num cell-uses" }, track, h("span", { class: "cell-num" }, fmtInt(r.uses))),
          h("td", { class: "num" }, fmtShare(r.uses, total)),
          h("td", { class: "num" }, fmtInt(r.active)),
          h("td", { class: "num" }, attempts ? fmtRate(r.error_pct, 2) : "—", attempts ? h("small", {}, `${fmtInt(r.errors)} de ${fmtInt(attempts)}`) : null, r.errors && attempts < SMALL_SAMPLE ? h("small", { class: "small-sample" }, "muestra pequeña") : null),
          h("td", {}, h("button", { type: "button", class: "btn btn-quiet btn-xs", "aria-pressed": String(on), onclick: () => setFilters({ version: on ? "" : r.version }) }, on ? "Quitar filtro" : "Filtrar")));
      }))))));
  root.append(goTo("Ver el historial de cambios", () => nav("updates")));
  return root;
}
