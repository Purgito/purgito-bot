// Actualizaciones: notas de lanzamientos y cambios para interpretar lo que muestran los gráficos.
import { badge, emptyState } from "../components.mjs";
import { h } from "../dom.mjs";
import { fmtDateTime, toLocalInput } from "../format.mjs";

const KINDS = {
  release: ["Versión publicada", "good"],
  change: ["Cambio relevante", "neutral"],
  manual_observation: ["Observación manual", "muted"],
};

export function updates({ data, model, saveAnnotation }) {
  const root = h("div", { class: "grid grid-wide" });
  const notes = [...model.annotations].sort((a, b) => b.t - a.t);

  const list = notes.length
    ? h("ol", { class: "timeline" }, notes.map((n) => {
        const [label, tone] = KINDS[n.kind] || [n.kind, "neutral"];
        return h("li", {}, h("div", { class: "tl-meta" }, h("time", { datetime: n.at }, fmtDateTime(n.t)), badge(label, tone), n.version ? h("code", {}, n.version) : null), h("h3", { class: "tl-title" }, n.title), n.note ? h("p", { class: "tl-note" }, n.note) : null);
      }))
    : emptyState({ title: "Sin anotaciones en este período", text: "Registra cada despliegue o cambio relevante. Así, cuando un gráfico se mueva, podrás ver qué había cambiado justo antes." });
  root.append(h("section", { class: "panel" }, h("header", { class: "panel-head" }, h("div", {}, h("h2", { class: "panel-title" }, "Cambios registrados"), h("p", { class: "panel-sub" }, "También aparecen como ◆ en los gráficos de tiempo"))), h("div", { class: "panel-body" }, list)));

  const error = h("p", { class: "form-error", role: "alert", hidden: true });
  const counter = h("span", { class: "counter" }, "0 / 1000");
  const field = (label, control, hint) => h("label", { class: "field" }, h("span", { class: "field-label" }, label), control, hint ? h("span", { class: "field-hint" }, hint) : null);
  const title = h("input", { class: "input", name: "title", required: true, maxlength: 120, autocomplete: "off" });
  const at = h("input", { class: "input", name: "at", type: "datetime-local", required: true, value: toLocalInput(model.nowMs) });
  const kind = h("select", { class: "input", name: "kind" }, Object.entries(KINDS).map(([v, [t]]) => h("option", { value: v }, t)));
  const version = h("input", { class: "input", name: "version", maxlength: 80, autocomplete: "off", placeholder: "Opcional" });
  const note = h("textarea", { class: "input", name: "note", rows: 4, maxlength: 1000, oninput: () => { counter.textContent = `${note.value.length} / 1000`; } });
  const submit = h("button", { type: "submit", class: "btn btn-primary" }, "Guardar anotación");
  const form = h("form", { class: "form", novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    error.hidden = true;
    if (!title.value.trim() || !at.value) {
      error.textContent = "Indica un título y una fecha.";
      error.hidden = false;
      return;
    }
    submit.disabled = true;
    try {
      await saveAnnotation({ at: `${at.value}:00Z`, title: title.value.trim(), note: note.value, version: version.value.trim(), kind: kind.value });
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      submit.disabled = false;
    }
  } },
  field("Título", title), field("Fecha y hora (UTC)", at), field("Tipo", kind), field("Versión", version), field("Nota", note, h("span", {}, "Texto plano, sin datos personales ni tokens. ", counter)), error, submit);
  root.append(h("section", { class: "panel" }, h("header", { class: "panel-head" }, h("div", {}, h("h2", { class: "panel-title" }, "Registrar un cambio"), h("p", { class: "panel-sub" }, "Se guarda en el PostgreSQL del bot"))), h("div", { class: "panel-body" }, form)));
  return root;
}
