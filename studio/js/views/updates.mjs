// Actualizaciones: historial cronológico de despliegues, cambios y observaciones. Cada entrada aparece
// también como glifo en los gráficos de tiempo. Registrar es una acción puntual (panel lateral).
import { noteIcon, NOTE_KIND } from "../charts.mjs";
import { emptyNote, icon, segmented } from "../components.mjs";
import { h } from "../dom.mjs";
import { fmtDayLong, fmtHour, toLocalInput } from "../format.mjs";
import { versionLabel } from "./versions.mjs";

const ui = { kind: "", saved: null };

function form(ctx) {
  const { model, saveAnnotation, closeSheet } = ctx;
  const error = h("p", { class: "form-error", role: "alert", hidden: true });
  const counter = h("span", { class: "counter" }, "0 / 1000");
  const field = (label, control, hint) => h("label", { class: "field" }, h("span", { class: "field-label" }, label), control, hint ? h("span", { class: "field-hint" }, hint) : null);
  const title = h("input", { class: "input", name: "title", required: true, maxlength: 120, autocomplete: "off" });
  const at = h("input", { class: "input", name: "at", type: "datetime-local", required: true, value: toLocalInput(model.nowMs) });
  const kind = h("select", { class: "input", name: "kind" }, Object.entries(NOTE_KIND).map(([v, k]) => h("option", { value: v }, k.label)));
  const version = h("input", { class: "input mono", name: "version", maxlength: 80, autocomplete: "off", placeholder: "Opcional, p. ej. ca7215a" });
  const note = h("textarea", { class: "input", name: "note", rows: 5, maxlength: 1000, oninput: () => { counter.textContent = `${note.value.length} / 1000`; } });
  const submit = h("button", { type: "submit", class: "btn btn-primary" }, "Guardar anotación");
  return h("form", { class: "form", novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    error.hidden = true;
    if (!title.value.trim() || !at.value) {
      error.textContent = "Indica un título y una fecha.";
      error.hidden = false;
      return;
    }
    submit.disabled = true;
    submit.textContent = "Guardando…";
    try {
      ui.saved = title.value.trim();
      await saveAnnotation({ at: `${at.value}:00Z`, title: title.value.trim(), note: note.value, version: version.value.trim(), kind: kind.value });
      closeSheet();
    } catch (err) {
      ui.saved = null;
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      submit.disabled = false;
      submit.textContent = "Guardar anotación";
    }
  } },
  field("Título", title),
  h("div", { class: "form-row" }, field("Fecha y hora (UTC)", at), field("Tipo", kind)),
  field("Versión", version),
  field("Nota", note, h("span", {}, "Texto plano, sin datos personales ni tokens. ", counter)),
  error,
  h("div", { class: "form-actions" }, submit, h("button", { type: "button", class: "btn btn-quiet", onclick: closeSheet }, "Cancelar")));
}

export function updates(ctx) {
  const { model, openSheet } = ctx;
  const root = h("div", { class: "page page-updates" });
  const open = () => openSheet("Registrar un cambio", [h("p", { class: "dlg-lead" }, "Se guarda en el PostgreSQL del bot y aparece en todos los gráficos de tiempo."), form(ctx)]);
  const all = [...model.annotations].sort((a, b) => b.t - a.t);
  const notes = all.filter((n) => !ui.kind || n.kind === ui.kind);
  const counts = Object.fromEntries(Object.keys(NOTE_KIND).map((k) => [k, all.filter((n) => n.kind === k).length]));

  root.append(h("div", { class: "toolbar toolbar-split" },
    all.length ? segmented("note-kind", [["", `Todo (${all.length})`], ...Object.entries(NOTE_KIND).map(([k, v]) => [k, `${v.label.split(" ")[0]}${counts[k] ? ` (${counts[k]})` : ""}`])], ui.kind, (v) => { ui.kind = v; ctx.rerender(); }, "Tipo de entrada", { small: true }) : h("span", {}),
    h("button", { type: "button", class: "btn btn-primary", id: "new-note", "aria-haspopup": "dialog", onclick: open }, icon("plus", { size: 16 }), "Registrar un cambio")));

  if (ui.saved) {
    root.append(h("p", { class: "notice is-ok", role: "status" }, `Anotación guardada: «${ui.saved}».`));
    queueMicrotask(() => (ui.saved = null));
  }

  if (!all.length) {
    root.append(emptyNote({ title: "Sin anotaciones en este período", text: "Registra cada despliegue o cambio relevante: cuando un gráfico se mueva, verás qué había cambiado justo antes." }));
    return root;
  }
  if (!notes.length) {
    root.append(h("p", { class: "empty-text" }, "Ninguna entrada de este tipo en el período."));
    return root;
  }
  const days = new Map();
  for (const n of notes) {
    const key = new Date(n.t).toISOString().slice(0, 10);
    (days.get(key) || days.set(key, []).get(key)).push(n);
  }
  root.append(h("ol", { class: "log" }, [...days].map(([day, items]) => h("li", { class: "log-day" },
    h("h2", { class: "log-date" }, h("time", { datetime: day }, fmtDayLong(`${day}T00:00:00Z`))),
    h("ol", { class: "timeline" }, items.map((n) => h("li", { class: `entry entry-${n.kind}` },
      h("span", { class: "entry-glyph" }, noteIcon(n.kind)),
      h("div", { class: "entry-body" },
        h("p", { class: "entry-meta" }, h("time", { datetime: n.at }, `${fmtHour(n.t)} UTC`), h("span", { class: "entry-kind" }, NOTE_KIND[n.kind]?.label || n.kind), n.version ? versionLabel(n.version) : null),
        h("h3", { class: "entry-title" }, n.title),
        n.note ? h("p", { class: "entry-note" }, n.note) : null))))))));
  return root;
}
