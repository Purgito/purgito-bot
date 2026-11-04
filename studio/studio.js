// Sin dependencias, HTML de datos ni almacenamiento de credenciales.
const $ = (id) => document.getElementById(id);
const fmt = (n) =>
  n == null ? "Sin datos" : new Intl.NumberFormat("es").format(n);
const pct = (n) => (n == null ? "No calculable" : `${fmt(n)} %`);
const date = (v) =>
  v
    ? new Date(v).toLocaleString("es", { timeZone: "UTC" }) + " UTC"
    : "Sin observación";
const labels = {
  overview: "Resumen",
  growth: "Comunidades",
  retention: "Retención",
  features: "Funciones",
  reliability: "Calidad",
  versions: "Versiones",
  updates: "Actualizaciones",
};
let data,
  view = "overview",
  pending;
function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function span(seconds) {
  const d = Math.floor(seconds / 86400),
    h = Math.floor((seconds % 86400) / 3600),
    m = Math.floor((seconds % 3600) / 60);
  return [d && `${d} d`, h && `${h} h`, !d && `${m} min`]
    .filter(Boolean)
    .join(" ");
}
function coverageNote(label, cov) {
  if (cov.status === "complete" && !cov.gap_count) return null;
  const state = {
    complete: "completa con huecos menores",
    partial: "parcial",
    unavailable: "insuficiente",
  }[cov.status];
  return (
    `${label}: cobertura ${state} (${(cov.ratio * 100).toFixed(1)} %` +
    `${cov.gap_count ? `; ${cov.gap_count} hueco(s), ${span(cov.gap_seconds)} sin captura, el mayor de ${span(cov.longest_gap_seconds)}` : ""}` +
    `${cov.dropped ? `; ${fmt(cov.dropped)} registros descartados` : ""}).`
  );
}
function panel(title) {
  const e = el("article", null, "card");
  e.append(el("h2", title));
  return e;
}
function empty(parent, text = "Todavía no hay observaciones en este período.") {
  parent.append(el("p", text, "empty"));
}
function table(headers, rows) {
  const wrap = el("div", null, "table-wrap"),
    t = el("table"),
    head = el("tr");
  headers.forEach((h) => head.append(el("th", h)));
  const thead = el("thead");
  thead.append(head);
  t.append(thead);
  const body = el("tbody");
  rows.forEach((r) => {
    const tr = el("tr");
    r.forEach((c) => tr.append(el("td", c)));
    body.append(tr);
  });
  t.append(body);
  wrap.append(t);
  if (!rows.length) empty(wrap);
  return wrap;
}
function metric(name, value, note, delta) {
  const c = el("article", null, "card");
  c.append(
    el("div", name, "metric-label"),
    el("div", value, "value"),
    el("div", note, "muted"),
  );
  if (delta === null)
    c.append(
      el("div", "Sin comparación: cobertura insuficiente en un período", "delta"),
    );
  else if (delta)
    c.append(
      el(
        "div",
        delta.pct == null
          ? "Sin base comparable"
          : `${delta.status === "partial" ? "≈ " : ""}${delta.difference >= 0 ? "+" : ""}${fmt(delta.difference)} · ${pct(delta.pct)} frente al período anterior${delta.status === "partial" ? " (solo lo observado: cobertura parcial, no es una estimación representativa)" : ""}`,
        "delta",
      ),
    );
  return c;
}
function chart(title, rows, key) {
  const p = panel(title);
  if (!rows.length) {
    empty(p);
    return p;
  }
  const ns = "http://www.w3.org/2000/svg",
    svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 700 210");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", title + "; tabla de valores debajo");
  svg.classList.add("chart");
  const max = Math.max(1, ...rows.map((r) => r[key] || 0));
  const points = rows.map(
    (r, i) =>
      `${20 + (i * 660) / Math.max(1, rows.length - 1)},${185 - ((r[key] || 0) * 160) / max}`,
  );
  for (const y of [25, 105, 185]) {
    const line = document.createElementNS(ns, "line");
    ["x1", "x2", "y1", "y2"].forEach((a, i) =>
      line.setAttribute(a, [20, 680, y, y][i]),
    );
    svg.append(line);
  }
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", points.join(" "));
  svg.append(line);
  if (rows.length === 1) {
    const dot = document.createElementNS(ns, "circle");
    const [x, y] = points[0].split(",");
    dot.setAttribute("cx", x);
    dot.setAttribute("cy", y);
    dot.setAttribute("r", "4");
    svg.append(dot);
  }
  p.append(svg);
  const range = el("div", null, "chart-labels");
  range.append(el("span", rows[0].day), el("span", rows.at(-1).day));
  p.append(range);
  const details = el("details");
  details.append(
    el("summary", "Ver valores medidos"),
    table(
      ["Día UTC", title],
      rows.map((r) => [r.day, fmt(r[key])]),
    ),
  );
  p.append(details);
  return p;
}
function render() {
  if (!data) return;
  const root = $("content");
  root.replaceChildren();
  $("title").textContent = labels[view];
  const cur = data.current,
    s = cur.summary;
  const cards = el("div", null, "cards");
  cards.append(
    metric(
      "Instalados · inventario global",
      fmt(data.latest_inventory?.installed),
      date(data.latest_inventory?.observed_at),
    ),
    metric(
      "Comunidades activas",
      fmt(s.active),
      "Uso exitoso iniciado por una persona",
      data.delta.active,
    ),
    metric(
      "Ejecuciones y entregas",
      fmt(s.uses),
      "Fuentes y resultados filtrados",
      data.delta.uses,
    ),
    metric(
      "Fallos de ejecución",
      pct(s.error_pct),
      `${fmt(s.errors)} fallos · ${fmt(s.refused)} rechazos de Discord (fuera de la tasa) · ${fmt(s.rejected)} validaciones previas`,
      data.delta.errors,
    ),
  );
  if (view === "overview") {
    root.append(cards);
    const grid = el("div", null, "layout");
    grid.append(chart("Uso observado por día", cur.daily, "uses"));
    const p = panel("Funciones con actividad");
    const top = cur.features
      .filter((f) => f.uses)
      .sort((a, b) => b.uses - a.uses)
      .slice(0, 7);
    if (!top.length) empty(p);
    top.forEach((f) => {
      const row = el("div", null, "bar"),
        bar = el("progress");
      bar.max = Math.max(...top.map((v) => v.uses));
      bar.value = f.uses;
      bar.setAttribute("aria-label", f.label);
      row.append(el("span", f.label), bar, el("strong", fmt(f.uses)));
      p.append(row);
    });
    grid.append(p);
    root.append(grid);
  }
  if (view === "growth") {
    root.append(
      el(
        "p",
        "Entradas, salidas y reingresos son transiciones observadas. El primer inventario no se cuenta como crecimiento. El filtro de función no cambia estas métricas.",
        "muted",
      ),
    );
    root.append(
      chart("Servidores instalados observados", data.inventory, "installed"),
    );
    const p = panel("Movimientos medidos");
    p.classList.add("wide");
    p.append(
      table(
        ["Día UTC", "Movimiento", "Cantidad"],
        data.growth.map((r) => [
          r.day,
          {
            join: "Entrada observada",
            leave: "Salida observada",
            rejoin: "Reingreso observado",
          }[r.action],
          fmt(r.n),
        ]),
      ),
    );
    root.append(p);
  }
  if (view === "retention") {
    const p = panel("Cohortes observadas · D1 / D7 / D28");
    p.append(
      el(
        "p",
        "Retención de actividad y presencia del bot son métricas distintas. «—» significa que el día no ha madurado o no tiene cobertura completa. «Primera actividad observada» no es la instalación: solo las cohortes «Entrada observada» (evento real de ingreso) y los servidores con entrada verificada son incorporaciones comprobadas. La «línea base» agrupa lo que ya existía cuando empezó la medición o cuando expiraron los datos anteriores; no son servidores nuevos.",
        "muted",
      ),
    );
    p.append(
      table(
        [
          "Cohorte UTC",
          "Tipo",
          "Comunidades",
          "Origen",
          "D1 activa / instalada",
          "D7 activa / instalada",
          "D28 activa / instalada",
        ],
        data.retention.map((r) => [
          r.day,
          r.kind === "activity"
            ? "Primera actividad observada"
            : "Entrada observada",
          fmt(r.size),
          r.kind !== "activity"
            ? "Entrada verificada"
            : r.baseline
              ? "Línea base: existían antes de la medición; no son nuevas"
              : `${fmt(r.joined_observed)} de ${fmt(r.size)} con entrada verificada`,
          ...r.horizons.map((h) =>
            h.eligible
              ? `${pct(h.active_pct)} / ${pct(h.installed_pct)}`
              : "— · sin cobertura suficiente",
          ),
        ]),
      ),
    );
    root.append(p);
  }
  if (view === "features") {
    const p = panel("Uso y adopción");
    p.append(
      el(
        "p",
        "Cero significa cero registros en la cobertura disponible, no que una función sea inútil. La adopción incluye comunidades atendidas por entregas automáticas; no las convierte en comunidades activas.",
        "muted",
      ),
    );
    p.append(
      table(
        [
          "Función",
          "Usos",
          "Comunidades atendidas",
          "Adopción observada",
          "Período anterior",
          "Cambio (puntos)",
          "Fallos",
          "Cobertura",
        ],
        cur.features.map((r) => [
          r.label,
          fmt(r.uses),
          fmt(r.served),
          pct(r.adoption_pct),
          pct(r.previous_adoption_pct),
          r.adoption_change_pp == null
            ? "Sin base comparable"
            : `${r.adoption_change_pp >= 0 ? "+" : ""}${fmt(r.adoption_change_pp)} pp`,
          fmt(r.errors),
          {
            commands_and_deliveries: "Comandos y entregas",
            commands: "Comandos",
            deliveries: "Entregas",
            explicit_events: "Eventos medidos",
            not_instrumented: "Sin instrumentar",
          }[r.coverage],
        ]),
      ),
    );
    root.append(p);
    const c = panel("Comandos");
    c.classList.add("wide");
    const seen = new Set(cur.commands.map((r) => `${r.source}:${r.command}`));
    const rows = cur.commands.map((r) => [
      r.command,
      r.source,
      fmt(r.uses),
      fmt(r.served),
      fmt(r.errors),
    ]);
    data.catalog
      .filter((c) => !seen.has(`${c.source}:${c.command}`))
      .forEach((c) =>
        rows.push([c.command, c.source, "Sin uso observado", "—", "—"]),
      );
    c.append(
      table(
        ["Comando", "Entrada", "Intentos", "Comunidades atendidas", "Fallos"],
        rows,
      ),
    );
    root.append(c);
  }
  if (view === "reliability") {
    root.append(cards);
    const p = panel("Errores y tiempos por función");
    p.append(
      el(
        "p",
        "Los fallos son errores que Purgito debe atender. Los rechazos de Discord (el bot sin permiso, canal o mensaje borrado) se muestran aparte y no entran en la tasa de fallo: indican configuración del servidor, pero siguen siendo visibles. Los permisos de quien invoca, argumentos o cooldown tampoco son errores del bot. p95 se estima con buckets y se muestra como límite superior. Las entregas sin temporizador no tienen latencia medida.",
        "muted",
      ),
    );
    p.append(
      table(
        [
          "Función",
          "Fallos",
          "Rechazos de Discord",
          "Validaciones previas",
          "Tasa de fallo",
          "Media",
          "p95",
          "Muestras",
        ],
        cur.features
          .filter((f) => f.uses)
          .map((r) => [
            r.label,
            fmt(r.errors),
            fmt(r.refused),
            fmt(r.rejected),
            pct(r.error_pct),
            r.mean_ms == null ? "—" : `${fmt(r.mean_ms)} ms`,
            r.p95_over_30000_ms
              ? "> 30 s"
              : r.p95_ms_upper_bound == null
                ? "—"
                : `≤ ${fmt(r.p95_ms_upper_bound)} ms`,
            fmt(r.samples),
          ]),
      ),
    );
    root.append(p);
  }
  if (view === "versions") {
    const p = panel("Evolución por versión");
    p.append(
      el(
        "p",
        "Una comparación entre versiones es descriptiva. No atribuye automáticamente un cambio de uso a una actualización; los períodos y la cobertura también cambian.",
        "muted",
      ),
    );
    p.append(
      table(
        [
          "Versión",
          "Usos",
          "Comunidades activas",
          "Éxitos",
          "Fallos",
          "Tasa de fallo",
        ],
        cur.versions.map((r) => [
          r.version,
          fmt(r.uses),
          fmt(r.active),
          fmt(r.successes),
          fmt(r.errors),
          pct(r.error_pct),
        ]),
      ),
    );
    root.append(p);
    root.append(chart("Uso observado por día", cur.daily, "uses"));
  }
  if (view === "updates") {
    const grid = el("div", null, "layout"),
      p = panel("Cambios para interpretar los resultados");
    const notes = el("div", null, "notes");
    if (!data.annotations.length)
      empty(notes, "Todavía no hay anotaciones en este período.");
    data.annotations.forEach((n) => {
      const note = el("article", null, "note");
      note.append(
        el("small", `${date(n.at)} · ${n.version || n.kind}`, "muted"),
        el("h3", n.title),
        el("p", n.note),
      );
      notes.append(note);
    });
    p.append(notes);
    grid.append(p);
    const formpanel = panel("Añadir una anotación"),
      form = el("form", null, "annotation-form");
    for (const [id, label, type] of [
      ["at", "Fecha UTC", "datetime-local"],
      ["title", "Título", "text"],
      ["version", "Versión (opcional)", "text"],
    ]) {
      const l = el("label", label),
        input = el("input");
      input.name = id;
      input.type = type;
      if (id === "at") input.value = new Date().toISOString().slice(0, 16);
      if (id !== "version") input.required = true;
      if (id === "title") input.maxLength = 120;
      l.append(input);
      form.append(l);
    }
    const noteLabel = el("label", "Nota (sin datos personales)"),
      note = el("textarea");
    note.name = "note";
    note.maxLength = 1000;
    noteLabel.append(note);
    form.append(noteLabel);
    const btn = el("button", "Guardar", "primary");
    btn.type = "submit";
    form.append(btn);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      btn.disabled = true;
      try {
        const body = Object.fromEntries(new FormData(form));
        body.at += ":00Z";
        await api("/internal/studio/annotations", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Studio-Request": "1",
          },
          body: JSON.stringify(body),
        });
        await load();
      } catch (err) {
        showNotice(err.message, true);
      } finally {
        btn.disabled = false;
      }
    });
    formpanel.append(form);
    grid.append(formpanel);
    root.append(grid);
  }
  $("definitions").replaceChildren();
  for (const [key, value] of Object.entries(data.definitions))
    $("definitions").append(
      el(
        "dt",
        {
          installed: "Instalación",
          active: "Actividad",
          adoption: "Adopción",
          retention: "Retención",
          errors: "Errores",
          latency: "Latencia",
          coverage: "Cobertura",
          scope: "Alcance",
        }[key] || key,
      ),
      el("dd", value),
    );
  root.setAttribute("aria-busy", "false");
}
function showNotice(text, error = false) {
  $("notice").replaceChildren(
    el("p", text, "notice" + (error ? " error" : "")),
  );
}
async function api(url, options = {}) {
  const res = await fetch(url, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
  });
  const body = await res.json().catch(() => ({ error: `Error ${res.status}` }));
  if (!res.ok) throw new Error(body.error || `Error ${res.status}`);
  return body;
}
async function load() {
  pending?.abort();
  const controller = new AbortController();
  pending = controller;
  $("content").setAttribute("aria-busy", "true");
  $("filters").querySelector("button").disabled = true;
  try {
    const params = new URLSearchParams();
    for (const key of ["start", "end", "version", "feature", "result"])
      if ($(key).value)
        params.set(
          key,
          ["start", "end"].includes(key) ? $(key).value + ":00Z" : $(key).value,
        );
    if ($("comparison").value === "custom") {
      if (!$("compare-end").value)
        throw new Error("Indica el fin del período de comparación");
      const hour = (value) => {
        const d = new Date(value);
        d.setUTCMinutes(0, 0, 0);
        return d;
      };
      const comparedEnd = hour($("compare-end").value + ":00Z");
      params.set("compare_end", comparedEnd.toISOString());
      params.set(
        "compare_start",
        new Date(
          comparedEnd - (hour(params.get("end")) - hour(params.get("start"))),
        ).toISOString(),
      );
    }
    data = await api("/internal/studio/report?" + params, {
      signal: controller.signal,
    });
    if (pending !== controller) return;
    for (const v of data.versions)
      if (![...$("version").options].some((o) => o.value === v))
        $("version").append(new Option(v, v));
    for (const f of data.current.features)
      if (![...$("feature").options].some((o) => o.value === f.feature))
        $("feature").append(new Option(f.label, f.feature));
    $("freshness").textContent = data.collector.last_flush
      ? "Último guardado " + date(data.collector.last_flush)
      : "Sin capturas todavía";
    $("period-label").textContent =
      `${date(data.period.start)} → ${date(data.period.end)} · Comparado con ${date(data.period.compare_start)} → ${date(data.period.compare_end)} · Agregación horaria UTC`;
    const warnings = [];
    if (data.collector.gateway_ready === false)
      warnings.push(
        "El bot está desconectado de Discord. Ese intervalo no cuenta como observación de uso.",
      );
    if (!data.coverage_started_at)
      warnings.push(
        "Todavía no comenzó la recopilación. No hay históricos que mostrar.",
      );
    for (const note of [
      coverageNote("Período actual", data.current.coverage),
      coverageNote("Período anterior", data.previous.coverage),
    ])
      if (note) warnings.push(note);
    if (data.comparison.status === "not_comparable")
      warnings.push(`Sin comparación: ${data.comparison.reason}`);
    else if (data.comparison.status === "partial")
      warnings.push(`Comparación parcial: ${data.comparison.reason}`);
    if (data.collector.dropped)
      warnings.push(
        `El buffer descartó ${fmt(data.collector.dropped)} registros; revisa la salud del colector.`,
      );
    if (data.collector.last_error)
      warnings.push(
        "Hay escrituras pendientes por un problema del almacenamiento local.",
      );
    if (warnings.length) showNotice(warnings.join(" "));
    else $("notice").replaceChildren();
    render();
  } catch (err) {
    if (err.name === "AbortError") return;
    showNotice(err.message, true);
    $("content").replaceChildren(
      el(
        "p",
        "No se muestran resultados anteriores como si fueran actuales. Usa Aplicar para reintentar.",
        "empty",
      ),
    );
    $("content").setAttribute("aria-busy", "false");
  } finally {
    if (pending === controller)
      $("filters").querySelector("button").disabled = false;
  }
}
const end = new Date();
end.setUTCSeconds(0, 0);
const start = new Date(end);
start.setUTCDate(start.getUTCDate() - 28);
$("start").value = start.toISOString().slice(0, 16);
$("end").value = end.toISOString().slice(0, 16);
$("filters").addEventListener("submit", (e) => {
  e.preventDefault();
  load();
});
$("comparison").addEventListener("change", () => {
  $("compare-label").hidden = $("comparison").value !== "custom";
});
$("nav").addEventListener("click", (e) => {
  const b = e.target.closest("[data-view]");
  if (!b) return;
  view = b.dataset.view;
  for (const button of $("nav").querySelectorAll("button"))
    button.removeAttribute("aria-current");
  b.setAttribute("aria-current", "page");
  render();
});
load();
