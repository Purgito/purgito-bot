// Orquestador: navegación, contexto del período (regla, comparación y filtros), carga de datos,
// diálogos y estado de la medición.
import { ApiError, getCommands, getReport, postAnnotation } from "./api.mjs";
import { coverageStrip, hideTip, noteIcon, NOTE_KIND, periodRuler } from "./charts.mjs";
import { closeHelps, icon } from "./components.mjs";
import { buildModel, COVERAGE_LABEL } from "./derive.mjs";
import { clear, h } from "./dom.mjs";
import { buildHash, emptyFilters, fetchKey, GROUPS, parseHash, PRESETS, rangeFor, toQuery, VIEWS } from "./filters.mjs";
import { ago, fmtDateTime, fmtDay, fmtDuration, fmtInt, fmtPct, shortVersion, toLocalInput } from "./format.mjs";
import { DAY, HOUR } from "./scale.mjs";
import { communities } from "./views/communities.mjs";
import { commands } from "./views/commands.mjs";
import { features } from "./views/features.mjs";
import { overview } from "./views/overview.mjs";
import { reliability } from "./views/reliability.mjs";
import { retention } from "./views/retention.mjs";
import { updates } from "./views/updates.mjs";
import { versions } from "./views/versions.mjs";

const RENDERERS = { overview, growth: communities, retention, features, commands, reliability, versions, updates };
const $ = (id) => document.getElementById(id);
const REFRESH_MS = 60_000;
const RESULT_LABEL = { ok: "Correcto", error: "Fallo", refused: "Rechazo de Discord", rejected: "Validación previa" };

const state = { view: "overview", filters: emptyFilters(), data: null, cmds: null, cmdsKey: "", model: null, key: "", controller: null, coverageStart: null, error: null };

/* ----------------------------------------------------------------- shell */

function buildNav() {
  const groups = Object.entries(GROUPS).map(([group, name]) => h("li", { class: "nav-group" },
    h("p", { class: "nav-group-label", id: `nav-${group}` }, name),
    h("ul", { "aria-labelledby": `nav-${group}` }, Object.entries(VIEWS).filter(([, v]) => v.group === group).map(([id, v]) =>
      h("li", {}, h("a", { href: buildHash(id, state.filters), "data-view": id }, icon(v.icon), h("span", {}, v.title)))))));
  clear($("nav"), groups);
}

function syncNav() {
  for (const a of $("nav").querySelectorAll("a")) {
    const id = a.dataset.view;
    a.href = buildHash(id, state.filters);
    if (id === state.view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  $("title").textContent = VIEWS[state.view].title;
  document.title = `${VIEWS[state.view].title} · Purgito Studio`;
  document.body.dataset.view = state.view;
}

function setMenu(open) {
  const side = $("sidebar");
  if (open) side.setAttribute("data-open", "");
  else side.removeAttribute("data-open");
  $("scrim").hidden = !open;
  $("menu").setAttribute("aria-expanded", String(open));
  if (open) side.querySelector("a")?.focus();
}

/* --------------------------------------------------------------- período */

function buildFilterBar() {
  const f = state.filters;
  const presetOptions = [...PRESETS.map((p) => [p.id, p.label]), ["since", "Desde el inicio"]];
  const presets = h("fieldset", { class: "seg seg-period" }, h("legend", { class: "sr-only" }, "Período"),
    presetOptions.map(([id, label]) => h("label", {}, h("input", { type: "radio", name: "preset", value: id, checked: f.preset === id ? true : null, onchange: () => navigate({ preset: id }) }), h("span", {}, label))));

  const start = h("input", { class: "input", type: "datetime-local", id: "c-start", value: f.start || "" });
  const end = h("input", { class: "input", type: "datetime-local", id: "c-end", value: f.end || "" });
  const cmpEnd = h("input", { class: "input", type: "datetime-local", id: "c-cmp", value: f.compareEnd || "" });
  const customError = h("p", { class: "form-error", role: "alert", hidden: true });
  const details = h("details", { class: "custom pop", ...(f.preset === "custom" ? { "data-active": "" } : {}) },
    h("summary", { class: "pop-summary" }, "Personalizado"),
    h("div", { class: "popover popover-end" },
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Desde (UTC)"), start),
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Hasta (UTC)"), end),
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Fin del período a comparar"), cmpEnd, h("span", { class: "field-hint" }, "Opcional. Por defecto, el período anterior de igual duración.")),
      customError,
      h("button", { type: "button", class: "btn btn-primary", onclick: () => {
        try {
          rangeFor({ preset: "custom", start: start.value, end: end.value }, Date.now());
        } catch (err) {
          customError.textContent = err.message;
          customError.hidden = false;
          return;
        }
        customError.hidden = true;
        details.open = false;
        navigate({ preset: "custom", start: start.value, end: end.value, compareEnd: cmpEnd.value });
      } }, "Aplicar período")));
  if (f.preset === "custom" && !start.value) {
    start.value = toLocalInput(Date.now() - 7 * DAY);
    end.value = toLocalInput(Date.now());
  }
  clear($("filters"), presets, details);
}

function navigate(patch, view = state.view) {
  state.filters = { ...state.filters, ...patch };
  const hash = buildHash(view, state.filters);
  if (location.hash === hash) apply();
  else location.hash = hash;
}

/* ------------------------------------------------------ contexto del período */

function filterControls() {
  const f = state.filters;
  const select = (id, label, key, options, all = "Todas") => h("label", { class: "field" }, h("span", { class: "field-label" }, label),
    h("select", { class: "input", id, onchange: (e) => navigate({ [key]: e.target.value }) }, h("option", { value: "" }, all), options.map(([v, t]) => h("option", { value: v, selected: v === f[key] ? true : null }, t))));
  const verOptions = (state.data?.versions || []).map((v) => [v, shortVersion(v)]);
  if (f.version && !verOptions.some(([v]) => v === f.version)) verOptions.push([f.version, f.version]);
  const featOptions = (state.data?.current.features || []).filter((x) => x.coverage !== "not_instrumented").map((x) => [x.feature, x.label]).sort((a, b) => a[1].localeCompare(b[1], "es"));
  if (f.feature && !featOptions.some(([v]) => v === f.feature)) featOptions.push([f.feature, f.feature]);
  const count = [f.version, f.feature, f.result].filter(Boolean).length;
  const panel = h("details", { class: "pop filters-pop" },
    h("summary", { class: "pop-summary" }, icon("filter", { size: 16 }), "Filtros", count ? h("span", { class: "count" }, String(count)) : null),
    h("div", { class: "popover" },
      select("f-version", "Versión", "version", verOptions),
      select("f-feature", "Función", "feature", featOptions),
      select("f-result", "Resultado", "result", Object.entries(RESULT_LABEL), "Todos"),
      h("p", { class: "field-hint" }, "Comunidades usa solo el filtro de versión."),
      count ? h("button", { type: "button", class: "btn btn-quiet", onclick: () => navigate({ version: "", feature: "", result: "" }) }, "Quitar filtros") : null));
  const featLabel = (id) => state.data?.current.features.find((x) => x.feature === id)?.label || id;
  const chips = [
    f.version && ["version", "Versión", shortVersion(f.version)],
    f.feature && ["feature", "Función", featLabel(f.feature)],
    f.result && ["result", "Resultado", RESULT_LABEL[f.result] || f.result],
  ].filter(Boolean).map(([key, name, value]) => h("span", { class: "chip" }, h("span", { class: "chip-name" }, `${name}:`), " ", value,
    h("button", { type: "button", class: "chip-x", "aria-label": `Quitar filtro ${name}: ${value}`, onclick: () => navigate({ [key]: "" }) }, icon("close", { size: 14 }))));
  return [panel, chips.length ? h("div", { class: "chips" }, chips) : null];
}

function qualityBar() {
  const q = $("quality");
  const data = state.data;
  const model = state.model;
  if (!data) return clear(q, ...filterControls());
  const cov = data.current.coverage;
  const pct = `${Math.floor(cov.ratio * 1000) / 10}`.replace(".", ",");
  const never = !model.measuring;
  const statusText = never ? "Aún sin mediciones" : cov.status === "complete"
    ? (cov.gap_count ? `Cobertura completa, ${pct} %` : "Cobertura completa")
    : cov.status === "partial" ? `Cobertura parcial, ${pct} %` : `Cobertura insuficiente, ${pct} %`;
  const unit = model.step === "hour" ? "por hora" : "por día";
  const ruler = h("button", { type: "button", class: `ruler cov-chip cov-${never ? "none" : cov.status}`, "aria-haspopup": "dialog", id: "coverage", onclick: openCoverage,
    "aria-label": never ? "Aún sin mediciones en este período. Ver detalle de cobertura" : `${COVERAGE_LABEL[cov.status]}: ${fmtPct(cov.ratio * 100)} del período medido${cov.gap_count ? `, ${cov.gap_count} ${cov.gap_count === 1 ? "hueco" : "huecos"}` : ""}. Ver detalle de cobertura` },
    h("span", { class: "ruler-date" }, fmtWhen(model.start, model.step)),
    periodRuler({ start: model.start, end: model.end, gaps: model.gaps, annotations: model.annotations }),
    h("span", { class: "ruler-date" }, fmtWhen(model.end, model.step, true)),
    h("span", { class: "ruler-status" }, h("span", { class: "sev", "aria-hidden": "true" }), statusText));

  const cmp = data.comparison;
  const on = state.filters.compare;
  const cmpRange = `${fmtDay(data.period.compare_start)} – ${fmtDay(Date.parse(data.period.compare_end) - 1)}`;
  const cmpState = cmp.status === "comparable" ? cmpRange : cmp.status === "partial" ? `${cmpRange}, solo lo observado` : null;
  const compare = h("label", { class: `switch cmp-${on ? cmp.status : "off"}`, title: on && cmp.reason ? cmp.reason : null },
    h("input", { type: "checkbox", id: "f-compare", role: "switch", checked: on ? true : null, onchange: (e) => navigate({ compare: e.target.checked }) }),
    h("span", { class: "switch-track", "aria-hidden": "true" }),
    h("span", { class: "switch-text" }, !on ? "Comparación desactivada" : cmpState ? ["Comparando con ", h("strong", {}, cmpState)] : "Comparación no disponible"));

  clear(q,
    h("div", { class: "context-main" }, ruler, h("span", { class: "grain" }, unit)),
    h("div", { class: "context-side" }, compare, ...filterControls()),
    model.degraded ? h("p", { class: "context-note", role: "note" }, "El bot en ejecución aún no envía la serie por horas (llegará con su próximo reinicio), así que se muestra por días.") : null);
}

function fmtWhen(t, step, end = false) {
  if (step === "hour") return fmtDateTime(t).replace(" UTC", "");
  return fmtDay(end ? t - 1 : t);
}

function freshness() {
  const box = $("freshness");
  const text = $("freshness-text");
  const col = state.data?.collector;
  if (state.error && !state.data) {
    box.dataset.state = "error";
    text.textContent = "Sin conexión con Studio";
    return;
  }
  if (!col) return;
  let status = "ok";
  let message;
  if (col.last_error) { status = "error"; message = "Error al guardar mediciones"; }
  else if (col.gateway_ready === false) { status = "stale"; message = "Bot desconectado de Discord"; }
  else if (!col.last_flush) { status = "off"; message = "Aún sin primer volcado"; }
  else if (Date.now() - Date.parse(col.last_flush) > 90_000) { status = "stale"; message = `Último volcado ${ago(col.last_flush)}`; }
  else message = "Midiendo";
  box.dataset.state = status;
  clear(text, message, status === "ok" ? h("span", { class: "freshness-sub" }, `último volcado ${ago(col.last_flush)}`) : null);
  const running = $("running");
  running.hidden = !col.version;
  clear(running, "En ejecución ", h("code", {}, shortVersion(col.version)));
}

function notice(text, { error = false, retry = false } = {}) {
  const slot = $("notice");
  if (!text) return clear(slot);
  clear(slot, h("p", { class: `notice${error ? " is-error" : ""}` }, text, retry ? h("button", { type: "button", class: "btn btn-quiet", onclick: () => load() }, "Reintentar") : null));
}

/* --------------------------------------------------------------- diálogos */

function dialog(node, title, body) {
  const close = h("button", { type: "button", class: "icon-btn", "aria-label": "Cerrar", onclick: () => node.close() }, icon("close"));
  clear(node, h("div", { class: "dlg-head" }, h("h2", { id: node.getAttribute("aria-labelledby") }, title), close), h("div", { class: "dlg-body" }, body));
  if (!node.open) node.showModal();
}

const DEFINITIONS = { installed: "Instalación", active: "Actividad", adoption: "Adopción", retention: "Retención", errors: "Errores", latency: "Latencia", coverage: "Cobertura", scope: "Alcance" };

function openGlossary() {
  const defs = state.data?.definitions || {};
  dialog($("glossary"), "Glosario", [
    h("p", { class: "dlg-lead" }, "Qué significa cada métrica y qué no. Studio mide el uso del bot; no sustituye al monitor operativo."),
    h("dl", { class: "glossary" }, Object.entries(defs).flatMap(([key, text]) => [h("dt", {}, DEFINITIONS[key] || key), h("dd", {}, text)])),
    h("h3", { class: "dlg-sub" }, "Marcas en los gráficos"),
    h("ul", { class: "glyph-legend" }, Object.entries(NOTE_KIND).map(([kind, k]) => h("li", {}, noteIcon(kind), k.label)),
      h("li", {}, h("span", { class: "hatch-sample", "aria-hidden": "true" }), "Sin medir: hueco de cobertura, nunca un cero"),
      h("li", {}, h("span", { class: "hollow-sample", "aria-hidden": "true" }), "Tramo medido solo en parte")),
  ]);
}

function windowDetail(label, cov, start, end) {
  return h("section", { class: "cov-window" },
    h("h3", { class: "dlg-sub" }, label, h("span", { class: "dlg-dates" }, `${fmtDateTime(start)} – ${fmtDateTime(end)}`)),
    coverageStrip(cov, Date.parse(start), Date.parse(end), { label: `${label}: ${COVERAGE_LABEL[cov.status]}` }),
    h("dl", { class: "facts" },
      h("div", {}, h("dt", {}, "Estado"), h("dd", {}, COVERAGE_LABEL[cov.status])),
      h("div", {}, h("dt", {}, "Medido"), h("dd", {}, `${fmtPct(cov.ratio * 100)} (${fmtDuration(cov.covered_seconds)} de ${fmtDuration(cov.window_seconds)})`)),
      h("div", {}, h("dt", {}, "Huecos"), h("dd", {}, cov.gap_count ? `${cov.gap_count}: ${fmtDuration(cov.gap_seconds)} sin captura (el mayor, ${fmtDuration(cov.longest_gap_seconds)})` : "Ninguno")),
      h("div", {}, h("dt", {}, "Registros descartados"), h("dd", {}, fmtInt(cov.dropped)))),
    cov.gaps.length ? h("ul", { class: "gap-list" }, cov.gaps.map((g) => h("li", {}, h("span", {}, `${fmtDateTime(g.start)} – ${fmtDateTime(g.end)}`), h("strong", {}, fmtDuration(g.seconds))))) : null,
    cov.gap_count > cov.gaps.length ? h("p", { class: "field-hint" }, `Se muestran los primeros ${cov.gaps.length} huecos.`) : null);
}

function openCoverage() {
  const d = state.data;
  if (!d) return;
  dialog($("coverage-dialog"), "Cobertura de la medición", [
    h("p", { class: "dlg-lead" }, "La cobertura es la parte del período con captura confirmada. Los huecos se muestran tal cual: nunca se rellenan ni cuentan como cero."),
    windowDetail("Período actual", d.current.coverage, d.period.start, d.period.end),
    windowDetail("Período anterior", d.previous.coverage, d.period.compare_start, d.period.compare_end),
    h("section", { class: "cov-window" }, h("h3", { class: "dlg-sub" }, "Cuándo se compara"),
      h("ul", { class: "gap-list" },
        h("li", {}, h("span", {}, "Comparable"), h("span", {}, "Ambos períodos ≥ 99,5 % y sin descartes")),
        h("li", {}, h("span", {}, "Solo lo observado"), h("span", {}, "Ambos ≥ 90 %, alguno parcial")),
        h("li", {}, h("span", {}, "Sin comparación"), h("span", {}, "Alguno por debajo del 90 %"))),
      d.comparison.reason ? h("p", { class: "field-hint" }, d.comparison.reason) : null),
  ]);
}

function openSheet(title, body) {
  dialog($("sheet"), title, body);
  queueMicrotask(() => $("sheet").querySelector("input, select, textarea")?.focus());
}

/* ------------------------------------------------------------------ carga */

function currentRange() {
  return rangeFor(state.filters, Date.now(), state.coverageStart);
}

async function bootstrap() {
  // Una consulta mínima para saber desde cuándo se mide y elegir un período útil por defecto.
  const end = Math.floor(Date.now() / 1000) * 1000;
  const query = new URLSearchParams({ start: new Date(end - 2 * HOUR).toISOString(), end: new Date(end).toISOString() });
  const data = await getReport(query);
  state.coverageStart = data.coverage_started_at ? Date.parse(data.coverage_started_at) : null;
  if (!state.filters.preset) {
    const young = state.coverageStart != null && Date.now() - state.coverageStart < 28 * DAY;
    state.filters.preset = young ? "since" : "28d";
    history.replaceState(null, "", buildHash(state.view, state.filters));
  }
}

async function load({ silent = false } = {}) {
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  if (!silent) {
    $("content").setAttribute("aria-busy", "true");
    document.body.dataset.loading = "";
  }
  try {
    if (!state.filters.preset || (state.coverageStart === null && state.filters.preset === "since")) await bootstrap();
    const range = currentRange();
    const query = toQuery(state.filters, range);
    // Los comandos tienen su propio endpoint (series y reparto por servidor): solo se piden en su vista.
    const [data, cmds] = await Promise.all([
      getReport(query, controller.signal),
      state.view === "commands" ? getCommands(query, controller.signal) : null,
    ]);
    if (state.controller !== controller) return;
    state.data = data;
    state.cmdsKey = cmds ? fetchKey(state.filters) : "";
    if (cmds) state.cmds = cmds;
    state.coverageStart = data.coverage_started_at ? Date.parse(data.coverage_started_at) : state.coverageStart;
    state.key = fetchKey(state.filters);
    state.error = null;
    notice(null);
    paint();
  } catch (err) {
    if (err.name === "AbortError") return;
    state.error = err;
    notice(err instanceof ApiError || err instanceof Error ? err.message : "Error inesperado", { error: true, retry: true });
    freshness();
    $("content").setAttribute("aria-busy", "false");
    if (!state.data) clear($("content"), h("p", { class: "empty-text pad" }, "No se muestran datos hasta poder consultar Studio."));
  } finally {
    if (state.controller === controller) delete document.body.dataset.loading;
  }
}

function visibleData() {
  const d = state.data;
  if (state.filters.compare) return d;
  // Sin comparar: se conservan los datos del período y se retira todo lo que dependa del anterior.
  return { ...d, delta: {}, comparison: { ...d.comparison, status: "not_comparable", reason: null } };
}

function paint() {
  const data = visibleData();
  state.model = buildModel(data, Date.now());
  syncNav();
  buildFilterBar();
  qualityBar();
  freshness();
  renderView(data);
}

function renderView(data = visibleData()) {
  hideTip();
  closeHelps();
  const content = $("content");
  const model = state.model;
  const ctx = {
    data, model, filters: state.filters, commands: state.cmdsKey === state.key ? state.cmds : null,
    nav: (view, patch = {}) => navigate(patch, view),
    setFilters: (patch) => navigate(patch),
    openCoverage,
    openSheet,
    closeSheet: () => $("sheet").close(),
    rerender: (opts = {}) => {
      renderView();
      if (opts.keepFocus) {
        const el = document.getElementById(opts.keepFocus);
        if (el) {
          el.focus();
          el.setSelectionRange?.(el.value.length, el.value.length);
        }
      }
    },
    saveAnnotation: async (body) => {
      await postAnnotation(body);
      await load();
    },
  };
  try {
    clear(content, RENDERERS[state.view](ctx));
  } catch (err) {
    console.error(err);
    clear(content, h("p", { class: "notice is-error" }, "No se pudo mostrar esta vista. Los datos no se han perdido: recarga la página."));
  }
  // Las tablas pueden desplazarse en horizontal en pantallas pequeñas: deben poder usarse con teclado.
  for (const wrap of content.querySelectorAll(".table-wrap")) {
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", `Tabla: ${wrap.querySelector("caption")?.textContent || "datos"}`);
  }
  content.setAttribute("aria-busy", "false");
}

/* ----------------------------------------------------------------- rutas */

function apply({ focus = false } = {}) {
  const parsed = parseHash(location.hash);
  const viewChanged = parsed.view !== state.view;
  state.view = parsed.view;
  state.filters = parsed.filters;
  syncNav();
  const key = fetchKey(state.filters);
  if (state.data && key === state.key && (state.view !== "commands" || state.cmdsKey === key)) {
    paint();
  } else {
    buildFilterBar();
    if (!state.data) qualityBar();
    load();
  }
  if (viewChanged || focus) {
    setMenu(false);
    $("title").focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }
}

function init() {
  buildNav();
  $("menu").append(icon("menu", { size: 20 }));
  $("close-menu").append(icon("close", { size: 20 }));
  $("menu").addEventListener("click", () => setMenu(true));
  $("close-menu").addEventListener("click", () => setMenu(false));
  $("scrim").addEventListener("click", () => setMenu(false));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    setMenu(false);
    for (const d of document.querySelectorAll("details.pop[open]")) d.open = false;
  });
  // Un solo desplegable abierto a la vez; un clic fuera lo cierra.
  document.addEventListener("click", (e) => {
    for (const d of document.querySelectorAll("details.pop[open]")) if (!d.contains(e.target)) d.open = false;
  });
  $("open-glossary").addEventListener("click", openGlossary);
  $("refresh").addEventListener("click", () => load());
  window.addEventListener("hashchange", () => apply());
  setInterval(() => {
    const busy = document.querySelector("dialog[open], details.pop[open]") || document.activeElement?.matches?.("input, textarea, select");
    if (!document.hidden && !busy && state.filters.preset !== "custom") load({ silent: true });
    else freshness();
  }, REFRESH_MS);
  apply();
}

init();
