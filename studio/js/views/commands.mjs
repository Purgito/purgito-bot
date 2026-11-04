// Comandos: qué usa de verdad la comunidad. Un ranking que se lee como un registro (no como una tabla
// genérica) y, a su lado, la ficha del comando elegido: cuánto se usa, cómo evoluciona, cuántas
// comunidades lo usan y de cuántas servidores depende. Solo nombres de comandos registrados: nunca
// argumentos, mensajes, personas ni servidores concretos.
import { legend, miniColumns, seriesTable, shareStrip, swatch, timeChart } from "../charts.mjs";
import { badge, chartOrTable, deltaChip, emptyNote, figure, goTo, help, icon, sectionHead, segmented } from "../components.mjs";
import {
  commandChange,
  commandGlyph,
  commandId,
  commandSeries,
  concentration,
  COMMAND_SORTS,
  deltaInfo,
  p95Interval,
  rankCommands,
  SMALL_COMMAND_SAMPLE,
  unusedCommands,
} from "../derive.mjs";
import { h } from "../dom.mjs";
import { ago, fmtDateTime, fmtInt, fmtMs, fmtRate, fmtShare, plural } from "../format.mjs";
import { C } from "../palette.mjs";
import { buckets } from "../scale.mjs";

const SOURCE = { prefix: "Prefijo", slash: "Slash" };
const SORT_LABEL = { uses: "Más usados", served: "Más comunidades", change: "Mayor cambio", errors: "Más fallos", name: "Nombre" };
const PAGE = 25;

const ui = { q: "", source: "", sort: "uses", limit: PAGE, metric: "uses", idleOpen: false, focus: null, reveal: false };

/** El comando tal como lo escribe quien lo usa: glifo atenuado y nombre en monoespaciada. */
function token(c, { large = false } = {}) {
  const glyph = commandGlyph(c.source);
  return h("code", { class: `cmd-token${large ? " cmd-token-lg" : ""}`, title: `${SOURCE[c.source] || c.source}${c.source === "prefix" ? " (prefijo por defecto «!»)" : ""}` },
    glyph ? h("span", { class: "cmd-glyph", "aria-hidden": "true" }, glyph) : null, h("span", {}, c.command),
    glyph ? h("span", { class: "sr-only" }, ` (${SOURCE[c.source]})`) : null);
}

function bar(value, max) {
  const track = h("span", { class: "cell-bar", "aria-hidden": "true" }, h("span", {}));
  track.firstChild.style.setProperty("--w", `${max ? Math.max(value > 0 ? 1.5 : 0, (100 * value) / max) : 0}%`);
  return track;
}

function changeChip(c, comparison) {
  const change = commandChange(c, comparison);
  if (!change) return null;
  if (change.kind === "new") return badge("nuevo", "accent", "No tuvo ejecuciones en el período anterior.");
  return deltaChip(change.info);
}

/* ------------------------------------------------------------------- cabecera */

function hero(ctx, cmds, catalog) {
  const { data } = ctx;
  // «De los N registrados» solo si el catálogo contiene lo que se usó: si no, la proporción no significa nada.
  const known = new Set(catalog.map(commandId));
  const catalogSize = cmds.commands.every((c) => known.has(commandId(c))) ? catalog.length : 0;
  const used = cmds.commands;
  const total = cmds.totals.current;
  const partial = data.current.coverage.status !== "complete";
  const top = used[0];
  const topTwo = used.length > 1 ? used[0].uses + used[1].uses : 0;
  const delta = (key) => {
    if (data.comparison.status === "not_comparable") return null;
    const a = cmds.totals.current[key];
    const b = cmds.totals.previous[key];
    return deltaInfo({ difference: a - b, pct: b ? Math.round((1000 * (a - b)) / b) / 10 : null, status: data.comparison.status }, null);
  };
  const attempts = total.successes + total.errors;
  return h("section", { class: "hero cmd-hero", "aria-labelledby": "ch-t" },
    h("h2", { class: "sr-only", id: "ch-t" }, "Resumen de comandos"),
    h("p", { class: "hero-statement" },
      h("span", { class: "hero-figure" }, fmtInt(used.length)),
      h("span", { class: "hero-words" }, used.length === 1 ? "comando distinto se usó" : "comandos distintos se usaron",
        h("span", { class: "hero-of" }, catalogSize
          ? `de los ${fmtInt(catalogSize)} registrados (${fmtShare(used.length, catalogSize, 0)})${used.length > 1 ? ` · los dos primeros reúnen el ${fmtShare(topTwo, total.uses, 0)} de las ejecuciones` : ""}`
          : "en el período elegido"))),
    partial ? h("div", { class: "hero-meta" }, h("span", { class: "minimum" }, "mínimo: parte del período sin medir")) : null,
    h("div", { class: "figures figures-4" },
      figure({ label: "Ejecuciones de comandos", value: fmtInt(total.uses), delta: delta("uses"), minimum: partial, info: "Intentos de comandos registrados, sea cual sea su resultado. No incluye las respuestas del chat ni las entregas automáticas." }),
      figure({ label: "Comunidades", value: fmtInt(total.served), unit: total.served === 1 ? "comunidad" : "comunidades", delta: delta("served"), note: data.current.observed_communities ? `de ${fmtInt(data.current.observed_communities)} observadas (${fmtShare(total.served, data.current.observed_communities, 0)})` : null, info: "Comunidades distintas con al menos un comando terminado correctamente." }),
      figure({ label: "Más usado", value: top ? h("span", { class: "fig-token" }, token(top)) : "—", note: top ? `${fmtShare(top.uses, total.uses, 0)} de las ejecuciones · ${plural(top.served, "comunidad", "comunidades")}` : "Sin ejecuciones" }),
      figure({ label: "Tasa de fallo", value: attempts ? fmtRate(100 * total.errors / attempts, 2) : "—", note: attempts ? `${fmtInt(total.errors)} de ${fmtInt(attempts)} intentos` : "Sin intentos", info: data.definitions?.errors })));
}

/* -------------------------------------------------------------------- ranking */

function spark(c, ctx, view) {
  const series = commandSeries(c, view.times, view.step, ctx.model.gaps);
  const unit = view.step === "hour" ? "hora" : "día";
  return miniColumns(series.uses, { color: C.current, height: 26, label: `Ejecuciones de ${commandGlyph(c.source)}${c.command} por ${unit}` });
}

function row(c, i, ctx, view, max, labels, selected) {
  const conc = concentration(c);
  const sel = commandId(c) === selected;
  const id = `crow-${i}`;
  const dependence = conc.kind === "single" ? "solo 1 servidor"
    : conc.kind === "none" ? null
      : `mayor: ${fmtShare(conc.top1, 1, 0)}`;
  return h("li", { class: `crow${sel ? " is-selected" : ""}` },
    h("button", { type: "button", class: "crow-btn", id, "aria-pressed": String(sel), "aria-controls": "cdetail",
      onclick: () => { ui.focus = id; ui.reveal = true; ctx.setFilters({ cmd: commandId(c) }); } },
      h("span", { class: "crow-rank", "aria-hidden": "true" }, String(i + 1)),
      h("span", { class: "crow-name" }, token(c), h("small", {}, labels[c.feature] || c.feature || "")),
      h("span", { class: "crow-spark" }, spark(c, ctx, view)),
      h("span", { class: "crow-uses" }, bar(c.uses, max), h("span", { class: "cell-num" }, fmtInt(c.uses))),
      h("span", { class: "crow-reach" }, h("span", { class: "cell-num" }, fmtInt(c.served)), dependence ? h("small", { class: conc.kind === "single" ? "is-single" : "" }, dependence) : null),
      h("span", { class: "crow-change" }, changeChip(c, ctx.data.comparison) || h("span", { class: "muted" }, "·"))));
}

function tools(ctx, sources, shown, all) {
  const search = h("label", { class: "search" }, icon("search", { size: 16 }),
    h("input", { type: "search", class: "input", id: "cmd-filter", placeholder: "Buscar comando o función", "aria-label": "Buscar comando o función", value: ui.q, autocomplete: "off",
      oninput: (e) => { ui.q = e.target.value; ui.limit = PAGE; ctx.rerender({ keepFocus: "cmd-filter" }); } }));
  const source = sources.length > 1
    ? segmented("cmd-source", [["", "Todos"], ...sources.map((s) => [s, SOURCE[s] || s])], ui.source, (v) => { ui.source = v; ui.limit = PAGE; ctx.rerender(); }, "Tipo de comando", { small: true })
    : null;
  const order = h("label", { class: "field field-inline" }, h("span", { class: "field-label" }, "Ordenar por"),
    h("select", { class: "input", id: "cmd-sort", onchange: (e) => { ui.sort = e.target.value; ui.limit = PAGE; ctx.rerender({ keepFocus: "cmd-sort" }); } },
      COMMAND_SORTS.map((v) => h("option", { value: v, selected: v === ui.sort ? true : null }, SORT_LABEL[v]))));
  return h("div", { class: "cmds-tools" }, search, source, order,
    h("p", { class: "cmds-count", "aria-live": "polite" }, shown === all ? plural(all, "comando", "comandos") : `${fmtInt(shown)} de ${fmtInt(all)}`));
}

/* ----------------------------------------------------------------------- ficha */

function dependence(c) {
  const conc = concentration(c);
  const parts = (c.top_shares || []).map((v, i) => ({ key: `s${i}`, label: `Servidor ${i + 1}`, value: v, color: `var(--cat-${i + 1})` }));
  const rest = Math.max(0, 1 - parts.reduce((a, p) => a + p.value, 0));
  if (rest > 0.0005) parts.push({ key: "rest", label: "Resto", value: rest, color: "var(--cat-other)" });
  let headline;
  if (conc.kind === "none") headline = "Sin intentos en el período.";
  else if (conc.kind === "single") headline = "Depende de un solo servidor: todos los intentos salen de él.";
  else if (conc.kind === "concentrated") headline = `Concentrado: un servidor aporta el ${fmtShare(conc.top1, 1, 0)} de los intentos, entre ${fmtInt(conc.guilds)}.`;
  else headline = `Repartido entre ${fmtInt(conc.guilds)} servidores: el mayor aporta el ${fmtShare(conc.top1, 1, 0)}.`;
  return h("section", { class: "cd-dep", "aria-labelledby": "cd-dep-t" },
    sectionHead("De cuántos servidores depende", { id: "cd-dep-t", level: 3, info: "Fracción de los intentos que aporta cada servidor, de mayor a menor. Los servidores no se identifican: solo importa cuántos son y cómo se reparten." }),
    h("p", { class: `cd-verdict cd-verdict-${conc.kind}` }, h("span", { class: "sev", "aria-hidden": "true" }), headline),
    conc.kind !== "none" ? [
      shareStrip(parts, { ariaLabel: `Reparto de los intentos entre servidores: ${parts.map((p) => `${p.label} ${fmtShare(p.value, 1, 0)}`).join(", ")}` }),
      h("dl", { class: "facts facts-compact" },
        h("div", {}, h("dt", {}, "Servidores que lo intentaron"), h("dd", {}, fmtInt(conc.guilds))),
        h("div", {}, h("dt", {}, "El mayor"), h("dd", {}, fmtShare(conc.top1, 1, 0))),
        conc.guilds > 3 ? h("div", {}, h("dt", {}, "Los tres mayores"), h("dd", {}, fmtShare(conc.top3, 1, 0))) : null)] : null,
    conc.small && conc.kind !== "none" ? h("p", { class: "field-hint" }, `Solo ${plural(c.uses, "intento", "intentos")}: con tan pocos datos la forma del reparto puede cambiar enseguida (menos de ${SMALL_COMMAND_SAMPLE}).`) : null);
}

function history(c, ctx, view) {
  const { model } = ctx;
  const series = commandSeries(c, view.times, view.step, model.gaps);
  const unit = view.step === "hour" ? "por hora" : "por día";
  const list = ui.metric === "uses"
    ? [{ key: "ok", name: "Correctas, rechazos y validaciones", values: series.ok, color: C.current }, { key: "errors", name: "Fallos", values: series.errors, color: C.error }]
    : [{ key: "served", name: "Comunidades que lo usaron", values: series.served, color: C.current }];
  const toggle = segmented("cmd-metric", [["uses", "Ejecuciones"], ["served", "Comunidades"]], ui.metric, (v) => { ui.metric = v; ctx.rerender(); }, "Métrica del gráfico", { small: true });
  const chart = timeChart({ times: view.times, step: view.step, series: list, kind: "columns", gaps: model.gaps, window: [model.start, model.end], annotations: model.annotations, label: `${ui.metric === "uses" ? "Ejecuciones" : "Comunidades"} de ${commandGlyph(c.source)}${c.command} ${unit}`, height: 220, unit: ui.metric === "uses" ? "usos" : "comunidades" });
  const { button, body } = chartOrTable(chart, seriesTable(view.times, view.step, list));
  const points = c.series.length;
  return h("section", { class: "cd-history", "aria-labelledby": "cd-hist-t" },
    sectionHead("Evolución", { id: "cd-hist-t", level: 3, sub: `${unit}, UTC`, actions: [toggle, button] }),
    list.length > 1 ? legend(list.map((i) => ({ name: i.name, color: i.color, kind: "box" }))) : null,
    body,
    points < 2 ? h("p", { class: "field-hint" }, "Todavía hay muy poco histórico de este comando: la serie crece conforme pasan las horas medidas. Los tramos sin medir no se rellenan.") : null);
}

function outcomes(c) {
  const ok = c.successes;
  const parts = [
    { key: "ok", label: "Correctas", value: ok, color: "var(--c-ok)" },
    { key: "error", label: "Fallos", value: c.errors, color: "var(--c-error)" },
    { key: "refused", label: "Rechazos de Discord", value: c.refused, color: "var(--c-refused)" },
    { key: "rejected", label: "Validaciones previas", value: c.rejected, color: "var(--c-rejected)" },
  ];
  return h("section", { class: "cd-out", "aria-labelledby": "cd-out-t" },
    sectionHead("Resultado", { id: "cd-out-t", level: 3 }),
    shareStrip(parts, { ariaLabel: `Resultado de los intentos: ${parts.map((p) => `${p.label} ${fmtInt(p.value)}`).join(", ")}` }),
    h("ul", { class: "out-list" }, parts.filter((p) => p.value > 0 || p.key === "ok").map((p) => h("li", {}, swatch(p.color, "box"), h("span", {}, p.label), h("strong", {}, fmtInt(p.value))))));
}

function detail(c, ctx, cmds, view, labels) {
  const { data } = ctx;
  const interval = p95Interval(c);
  const attempts = c.successes + c.errors;
  const sibling = cmds.commands.find((o) => o.command === c.command && o.source !== c.source);
  const change = commandChange(c, data.comparison);
  const first = c.first_seen ? Date.parse(c.first_seen) : null;
  const last = c.last_seen ? Date.parse(c.last_seen) + 3_600_000 : null;
  return h("article", { class: "cdetail", id: "cdetail", "aria-labelledby": "cd-name" },
    h("header", { class: "cd-head" },
      h("p", { class: "cd-kicker" }, "Comando · ", SOURCE[c.source] || c.source, labels[c.feature] ? ` · ${labels[c.feature]}` : ""),
      h("h2", { class: "cd-name", id: "cd-name" }, token(c, { large: true })),
      h("p", { class: "cd-seen" },
        first ? `Primera ejecución observada: ${fmtDateTime(first).replace(" UTC", "")} UTC` : "Sin ejecuciones observadas",
        last ? ` · última ${ago(Math.min(last, Date.now()))}` : "")),
    h("div", { class: "figures figures-2" },
      figure({ label: "Ejecuciones", value: fmtInt(c.uses), size: "md", delta: change?.kind === "delta" ? change.info : null, note: change?.kind === "new" ? "Sin ejecuciones en el período anterior" : null }),
      figure({ label: "Comunidades", value: fmtInt(c.served), note: c.previous && data.comparison.status !== "not_comparable" ? `${fmtInt(c.previous.served)} en el período anterior` : null }),
      figure({ label: "Tasa de fallo", value: attempts ? fmtRate(c.error_pct, 2) : "—", note: attempts ? `${fmtInt(c.errors)} de ${fmtInt(attempts)} intentos${attempts < 30 && c.errors ? " · muestra pequeña" : ""}` : "Sin intentos" }),
      figure({ label: "Latencia", value: fmtMs(c.mean_ms), note: interval ? (interval[1] ? `El 95 % entre ${fmtMs(interval[0])} y ${fmtMs(interval[1])}` : "El 5 % más lento supera 30 s") : "Sin muestras" })),
    history(c, ctx, view),
    dependence(c),
    outcomes(c),
    h("div", { class: "cd-actions" },
      sibling ? h("button", { type: "button", class: "btn btn-quiet", onclick: () => { ui.reveal = true; ctx.setFilters({ cmd: commandId(sibling) }); } },
        "También existe como ", h("code", {}, `${commandGlyph(sibling.source)}${sibling.command}`), ` · ${fmtInt(sibling.uses)} ${sibling.uses === 1 ? "uso" : "usos"}`) : null,
      c.feature ? h("button", { type: "button", class: "btn btn-quiet", onclick: () => ctx.nav("reliability", { feature: c.feature }) }, "Ver la calidad de su función") : null,
      c.feature ? h("button", { type: "button", class: "btn btn-quiet", onclick: () => ctx.nav("overview", { feature: c.feature }) }, "Ver su actividad en el tiempo") : null));
}

/* ------------------------------------------------------------- sin uso observado */

function idleSection(ctx, idle, labels, partial) {
  const q = ui.q.trim().toLowerCase().replace(/^[!/]/, "");
  const list = idle.filter((c) => (!ui.source || c.source === ui.source) && (!q || c.command.toLowerCase().includes(q) || String(labels[c.feature] ?? c.feature).toLowerCase().includes(q)));
  if (!idle.length) return null;
  const groups = new Map();
  for (const c of list) groups.set(c.feature, [...(groups.get(c.feature) || []), c]);
  const details = h("details", { class: "cidle", ...(ui.idleOpen ? { open: true } : {}) },
    h("summary", {}, h("span", { class: "cidle-title" }, "Registrados sin uso observado"), h("span", { class: "cidle-count" }, list.length === idle.length ? fmtInt(idle.length) : `${fmtInt(list.length)} de ${fmtInt(idle.length)}`)),
    h("p", { class: "field-hint" }, "Existen en el bot, pero no registraron ninguna ejecución en el período.", partial ? " Con la cobertura incompleta, «sin uso» no garantiza que nadie los haya usado." : ""),
    list.length ? [...groups].sort((a, b) => b[1].length - a[1].length).map(([feature, items]) => h("div", { class: "cidle-group" },
      h("h3", { class: "cidle-feature" }, labels[feature] || feature),
      h("ul", { class: "pills" }, items.sort((a, b) => a.command.localeCompare(b.command, "es")).map((c) => h("li", {}, token(c)))))) : h("p", { class: "empty-text" }, "Ninguno coincide con la búsqueda."));
  details.addEventListener("toggle", () => { ui.idleOpen = details.open; });
  return h("section", { class: "cidle-wrap", "aria-label": "Comandos sin uso observado" }, details);
}

/* ----------------------------------------------------------------------- vista */

export function commands(ctx) {
  const { data, model, filters } = ctx;
  const cmds = ctx.commands;
  const root = h("div", { class: "page page-commands" });
  if (!cmds) {
    root.append(emptyNote({ title: "Cargando los comandos…", text: "Un momento." }));
    return root;
  }
  const labels = Object.fromEntries(data.current.features.map((f) => [f.feature, f.label]));
  const catalog = data.catalog || [];
  const used = cmds.commands;
  const idle = unusedCommands(catalog, used);
  const partial = data.current.coverage.status !== "complete";
  if (!model.measuring) {
    root.append(emptyNote({ tone: "first", title: "Studio todavía no ha medido nada", text: "Cuando el bot empiece a medir, aquí aparecerá qué comandos usa la comunidad." }));
    return root;
  }
  if (!used.length) {
    root.append(hero(ctx, cmds, catalog));
    root.append(emptyNote({ title: "Sin comandos ejecutados en este período", text: partial ? "Con la cobertura incompleta no se puede afirmar que nadie los usara." : "Nadie ha ejecutado un comando registrado en este período." }));
    const quiet = idleSection(ctx, idle, labels, partial);
    if (quiet) root.append(quiet);
    return root;
  }

  const view = { step: cmds.step, times: buckets(model.start, model.end, cmds.step) };
  const ranked = rankCommands(used, { query: ui.q, source: ui.source, sort: ui.sort, featureLabel: (f) => labels[f] || f });
  const selected = ranked.find((c) => commandId(c) === filters.cmd) || used.find((c) => commandId(c) === filters.cmd) || ranked[0] || used[0];
  const shown = ranked.slice(0, ui.limit);
  if (ranked.length && !shown.includes(selected) && ranked.includes(selected)) shown.push(selected);
  const max = Math.max(1, ...used.map((c) => c.uses));
  const sources = [...new Set(used.map((c) => c.source))];
  const missing = filters.cmd && !used.some((c) => commandId(c) === filters.cmd);

  root.append(hero(ctx, cmds, catalog));
  root.append(h("div", { class: "cmd-layout" },
    h("section", { class: "cmd-rank", "aria-labelledby": "cr-t" },
      sectionHead("Ranking", { id: "cr-t", sub: "comandos registrados, nunca sus argumentos", info: "Cada fila es un comando tal como se escribe: «!» por prefijo y «/» por slash. Las ejecuciones cuentan todos los intentos; «mayor» es la fracción que aporta el servidor que más lo usa." }),
      tools(ctx, sources, ranked.length, used.length),
      missing ? h("p", { class: "field-hint", role: "status" }, `«${filters.cmd.replace(/^[a-z]+:/, "")}» no tuvo ejecuciones en este período; se muestra el primero del ranking.`) : null,
      ranked.length ? h("div", { class: "crows-head", "aria-hidden": "true" }, h("span", {}, "#"), h("span", {}, "Comando"), h("span", { class: "crow-spark" }, "Evolución"), h("span", {}, "Ejecuciones"), h("span", {}, "Comunidades"), h("span", {}, "Cambio")) : null,
      ranked.length
        ? h("ol", { class: "crows" }, shown.map((c, i) => row(c, ranked.indexOf(c) >= 0 ? ranked.indexOf(c) : i, ctx, view, max, labels, commandId(selected))))
        : h("p", { class: "empty-text" }, "Ningún comando coincide con la búsqueda."),
      shown.length < ranked.length ? h("button", { type: "button", class: "btn btn-quiet more", onclick: () => { ui.limit += PAGE; ctx.rerender(); } }, `Mostrar ${fmtInt(Math.min(PAGE, ranked.length - shown.length))} más de ${fmtInt(ranked.length - shown.length)}`) : null),
    h("div", { class: "cmd-side" }, detail(selected, ctx, cmds, view, labels))));
  const quiet = idleSection(ctx, idle, labels, partial);
  if (quiet) root.append(quiet);
  if (cmds.truncated) root.append(h("p", { class: "field-hint" }, "Se muestran los 300 comandos con más ejecuciones."));

  // Tras elegir un comando se conserva el foco y, en pantallas estrechas, se baja a su ficha.
  const focus = ui.focus;
  const reveal = ui.reveal;
  ui.focus = null;
  ui.reveal = false;
  queueMicrotask(() => {
    if (focus) document.getElementById(focus)?.focus({ preventScroll: true });
    if (reveal && window.matchMedia("(max-width: 1100px)").matches)
      document.getElementById("cdetail")?.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });
  return root;
}
