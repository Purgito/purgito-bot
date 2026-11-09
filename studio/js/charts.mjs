// Gráficos SVG/HTML sin dependencias. Reglas comunes: líneas de 2 px sin suavizado, columnas de hasta
// 24 px, rejilla hairline, texto siempre en tonos de texto (nunca en el color de la serie), los huecos de
// cobertura con la misma trama en todos los gráficos y las anotaciones con el mismo glifo por tipo.
import { clear, h, s, uid } from "./dom.mjs";
import { fmtCompact, fmtDateTime, fmtDay, fmtDuration, fmtInt, fmtMs, shortVersion } from "./format.mjs";
import {
  areaPath,
  DAY,
  HOUR,
  linear,
  linePath,
  nearestIndex,
  niceRange,
  niceTicks,
  niceTicksSigned,
  roundedBar,
  segments,
  timeTicks,
} from "./scale.mjs";

/* ------------------------------------------------------------------ tooltip */

let tip;
function tooltipNode() {
  tip ||= document.getElementById("tooltip") || document.body.appendChild(h("div", { id: "tooltip", class: "tooltip", role: "tooltip", hidden: true }));
  return tip;
}

export function showTip(content, clientX, clientY) {
  const node = tooltipNode();
  clear(node, content);
  node.hidden = false;
  const { width, height } = node.getBoundingClientRect();
  const margin = 12;
  let left = clientX + 16;
  if (left + width > window.innerWidth - margin) left = clientX - width - 16;
  const top = Math.min(Math.max(margin, clientY - height / 2), window.innerHeight - height - margin);
  node.style.setProperty("left", `${Math.max(margin, left)}px`);
  node.style.setProperty("top", `${top}px`);
}

export function hideTip() {
  tooltipNode().hidden = true;
}

export function swatch(color, kind = "line") {
  const key = h("span", { class: `key key-${kind}`, "aria-hidden": "true" });
  key.style.setProperty("--c", color);
  return key;
}

/** Fila de tooltip: el valor manda, el nombre acompaña. */
function tipRow(color, value, name, kind) {
  return h("div", { class: "tip-row" }, swatch(color, kind), h("strong", {}, value), h("span", { class: "tip-name" }, name));
}

/* ------------------------------------------------------------- anotaciones */

export const NOTE_KIND = {
  release: { label: "Versión publicada", glyph: "release" },
  change: { label: "Cambio relevante", glyph: "change" },
  manual_observation: { label: "Observación", glyph: "observation" },
};

/** Glifo de una anotación: rombo lleno (versión), rombo hueco (cambio), círculo hueco (observación). */
export function noteGlyph(kind, x, y, r = 5) {
  const g = NOTE_KIND[kind]?.glyph || "change";
  if (g === "observation") return s("circle", { cx: x, cy: y, r: r - 0.8, class: `glyph glyph-${g}` });
  return s("path", { d: `M${x} ${y - r}L${x + r} ${y}L${x} ${y + r}L${x - r} ${y}Z`, class: `glyph glyph-${g}` });
}

/** El mismo glifo como icono HTML (leyendas, listas). */
export function noteIcon(kind) {
  const svg = s("svg", { class: "note-icon", width: 12, height: 12, viewBox: "0 0 12 12", "aria-hidden": "true" });
  svg.append(noteGlyph(kind, 6, 6, 5));
  return svg;
}

function noteTip(a) {
  return h("div", { class: "tip-note tip-annotation" }, noteIcon(a.kind), h("span", {}, a.title, a.version ? h("span", { class: "tip-version" }, ` ${shortVersion(a.version)}`) : null));
}

/* --------------------------------------------------------------- responsive */

/** Redibuja con el ancho real del contenedor para que el texto no se escale ni se deforme. */
export function responsive(host, draw) {
  let width = 0;
  const render = () => {
    if (width > 0) host.replaceChildren(draw(width));
  };
  if (typeof ResizeObserver === "undefined") {
    width = 640;
    render();
    return render;
  }
  const observer = new ResizeObserver((entries) => {
    if (!host.isConnected) return observer.disconnect();
    const next = Math.floor(entries[0].contentRect.width);
    if (next !== width) {
      width = next;
      render();
    }
  });
  observer.observe(host);
  return render;
}

function hatchDefs(svg) {
  const id = uid("hatch");
  svg.append(s("defs", {}, s("pattern", { id, width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, s("line", { x1: 0, y1: 0, x2: 0, y2: 6, class: "hatch-line" }))));
  return `url(#${id})`;
}

/* -------------------------------------------------------------- time charts */

/**
 * Serie temporal. kind "line" (áreas/líneas) o "columns" (apiladas; side -1 dibuja bajo el cero).
 * series: [{ key, name, values, color, area?, muted?, side? }]. Un valor null es "no medido".
 */
export function timeChart(o) {
  const {
    times, step, series, kind = "line", yFormat = fmtInt, gaps = [], annotations = [],
    height = 232, label, integer = true, zero = true, window = null, unit = "", compact = false,
  } = o;
  const size = step === "hour" ? HOUR : DAY;
  // Fracción medida de cada tramo: descuenta lo que queda fuera de la ventana y los huecos de cobertura.
  const share = (i) => {
    const from = window ? Math.max(times[i], window[0]) : times[i];
    const to = window ? Math.min(times[i] + size, window[1]) : times[i] + size;
    if (to <= from) return 0;
    const missing = gaps.reduce((a, g) => a + Math.max(0, Math.min(to, g.end) - Math.max(from, g.start)), 0);
    return Math.max(0, to - from - missing) / size;
  };
  const isPartial = (i) => share(i) < 0.95;
  const host = h("div", { class: `chart${compact ? " chart-compact" : ""}`, tabindex: "0", role: "group", "aria-roledescription": "gráfico", "aria-label": `${label}. Usa las flechas para recorrer los valores.` });
  let active = null;
  let geometry = null;

  const bucketLabel = (i) => (step === "hour" ? fmtDateTime(times[i]) : fmtDay(times[i]));

  function tipContent(i) {
    const rows = series.map((item) => {
      const v = item.values[i];
      const kindKey = kind === "columns" ? "box" : item.muted ? "dash" : "line";
      return tipRow(item.color, v == null ? "Sin medición" : item.side === -1 ? `−${yFormat(v)}` : yFormat(v), item.name, kindKey);
    });
    const inGap = gaps.some((g) => g.start <= times[i] && g.end >= times[i] + size);
    const part = !inGap && share(i) < 0.999
      ? h("div", { class: "tip-note" }, `${isPartial(i) ? "Tramo parcial" : "Medido"}: ${fmtDuration((share(i) * size) / 1000)} de ${fmtDuration(size / 1000)}`)
      : null;
    const notes = annotations.filter((a) => a.t >= times[i] && a.t < times[i] + size).map(noteTip);
    return h("div", {}, h("div", { class: "tip-head" }, bucketLabel(i)), rows, inGap ? h("div", { class: "tip-note" }, "Sin cobertura en este tramo") : null, part, notes);
  }

  function setActive(index, announce = true) {
    active = index;
    if (!geometry) return;
    const { cross, dots, xs, svg, ys } = geometry;
    if (index == null) {
      cross.setAttribute("visibility", "hidden");
      dots.forEach((d) => d.setAttribute("visibility", "hidden"));
      hideTip();
      return;
    }
    const x = xs[index];
    cross.setAttribute("visibility", "visible");
    cross.querySelector("line").setAttribute("x1", x);
    cross.querySelector("line").setAttribute("x2", x);
    dots.forEach((dot, k) => {
      const y = ys[k][index];
      dot.setAttribute("visibility", y == null ? "hidden" : "visible");
      if (y != null) {
        dot.setAttribute("cx", x);
        dot.setAttribute("cy", y);
      }
    });
    if (announce) {
      const box = svg.getBoundingClientRect();
      showTip(tipContent(index), box.left + x, box.top + geometry.top + 24);
    }
  }

  function draw(width) {
    const m = { l: 44, r: 12, t: unit ? 22 : 12, b: 28 };
    const iw = Math.max(60, width - m.l - m.r);
    const ih = height - m.t - m.b;
    const columns = kind === "columns";

    let pos = 0;
    let neg = 0;
    if (columns) {
      for (let i = 0; i < times.length; i++) {
        let up = 0;
        let down = 0;
        for (const item of series) (item.side === -1 ? (down += item.values[i] || 0) : (up += item.values[i] || 0));
        pos = Math.max(pos, up);
        neg = Math.min(neg, -down);
      }
    } else {
      for (const item of series) for (const v of item.values) if (v != null) pos = Math.max(pos, v);
    }
    let scale;
    if (!zero && !columns) {
      const all = series.flatMap((item) => item.values.filter((v) => v != null));
      scale = niceRange(Math.min(...all), Math.max(...all));
    } else scale = neg < 0 ? niceTicksSigned(neg, pos, 4, integer) : niceTicks(pos, 4, integer);
    const yMin = scale.min ?? 0;
    const y = linear(yMin, scale.max, m.t + ih, m.t);
    const t0 = times[0];
    const t1 = times.at(-1) + (columns ? size : 0);
    const band = iw / Math.max(1, times.length);
    const x = times.length > 1 || columns ? linear(t0, t1, m.l, m.l + iw) : () => m.l + iw / 2;
    const xs = times.map((t) => (columns ? x(t) + band / 2 : x(t)));

    const svg = s("svg", { class: "plot", width, height, viewBox: `0 0 ${width} ${height}`, role: "img", "aria-hidden": "true" });
    const hatch = hatchDefs(svg);
    if (unit) svg.append(s("text", { x: m.l - 8, y: 11, class: "tick tick-unit", "text-anchor": "end" }, unit));

    for (const v of scale.ticks) {
      svg.append(s("line", { x1: m.l, x2: m.l + iw, y1: y(v), y2: y(v), class: v === 0 && zero ? "axis" : "gl" }));
      svg.append(s("text", { x: m.l - 8, y: y(v) + 4, class: "tick", "text-anchor": "end" }, fmtCompact(v)));
    }
    for (const g of gaps) {
      const from = Math.max(t0, g.start);
      const to = Math.min(columns ? t1 : times.at(-1), g.end);
      if (to <= from) continue;
      const gx = x(from);
      const gw = Math.max(2, x(to) - x(from));
      svg.append(s("rect", { x: gx, y: m.t, width: gw, height: ih, fill: hatch, class: "gap" }));
      if (gw > 54) svg.append(s("text", { x: gx + gw / 2, y: m.t + 12, class: "gap-label", "text-anchor": "middle" }, "sin medir"));
    }
    const stepTicks = timeTicks(t0, columns ? t1 - size : t1, step, Math.max(2, Math.floor(iw / 76)));
    for (const tick of stepTicks) {
      const tx = columns ? x(tick.t) + band / 2 : x(tick.t);
      svg.append(s("text", { x: tx, y: height - 8, class: tick.major ? "tick tick-major" : "tick", "text-anchor": "middle" }, tick.label));
    }

    const ys = series.map(() => times.map(() => null));
    const dots = [];
    if (columns) {
      const bw = Math.min(24, Math.max(2, band - Math.min(4, band * 0.3)));
      times.forEach((_, i) => {
        for (const sign of [1, -1]) {
          const group = series.filter((item) => (item.side === -1 ? -1 : 1) === sign && (item.values[i] || 0) > 0);
          let cum = 0;
          group.forEach((item, n) => {
            const v = item.values[i];
            const from = y(sign * cum);
            const to = y(sign * (cum + v));
            const last = n === group.length - 1;
            let top = Math.min(from, to);
            let hgt = Math.abs(from - to);
            if (hgt < 2) hgt = 2;
            if (!last) {
              if (sign === 1) hgt = Math.max(1, hgt - 2);
              else (top += 2), (hgt = Math.max(1, hgt - 2));
            }
            const px = xs[i] - bw / 2;
            const d = last ? roundedBar(px, top, bw, hgt, Math.min(3, bw / 2), sign === 1) : `M${px} ${top}h${bw}v${hgt}h${-bw}Z`;
            svg.append(s("path", { d, fill: item.color, class: isPartial(i) ? "bar bar-partial" : "bar" }));
            cum += v;
          });
        }
        series.forEach((item, k) => {
          ys[k][i] = item.values[i] == null ? null : y(item.side === -1 ? -item.values[i] : item.values[i]);
        });
      });
    } else {
      series.forEach((item, k) => {
        const ypx = item.values.map((v) => (v == null ? null : y(v)));
        ypx.forEach((v, i) => (ys[k][i] = v));
        const part = (i) => !item.muted && isPartial(i);
        const solid = ypx.map((v, i) => (part(i) ? null : v));
        for (const seg of segments(xs, solid)) {
          if (item.area && seg.length > 1) svg.append(s("path", { d: areaPath(seg, y(Math.max(0, yMin))), fill: item.color, class: "area" }));
          if (seg.length > 1) svg.append(s("path", { d: linePath(seg), stroke: item.color, class: item.muted ? "line line-muted" : "line" }));
          else svg.append(s("circle", { cx: seg[0][0], cy: seg[0][1], r: 3, fill: item.color, class: "dot" }));
        }
        // Un tramo parcial no es una caída: se une con trazo discontinuo y se marca con un punto hueco.
        for (let i = 0; i < ypx.length; i++) {
          if (!part(i) || ypx[i] == null) continue;
          for (const j of [i - 1, i + 1]) {
            if (j < 0 || j >= ypx.length || ypx[j] == null || (part(j) && j > i)) continue;
            svg.append(s("path", { d: linePath([[xs[i], ypx[i]], [xs[j], ypx[j]]]), stroke: item.color, class: "line line-partial" }));
          }
          if (!item.muted) svg.append(s("circle", { cx: xs[i], cy: ypx[i], r: 3.5, class: "dot-hollow", stroke: item.color }));
        }
        if (!item.muted) {
          const lastI = item.values.findLastIndex((v, i) => v != null && !part(i));
          if (lastI >= 0) svg.append(s("circle", { cx: xs[lastI], cy: ypx[lastI], r: 3.5, fill: item.color, class: "dot dot-end" }));
        }
      });
    }

    // Anotaciones: línea fina y glifo en el borde superior (no tapan el dato).
    for (const a of annotations) {
      if (a.t < t0 || a.t > t1) continue;
      const ax = x(a.t);
      const g = s("g", { class: "marker" }, s("line", { x1: ax, x2: ax, y1: m.t + 6, y2: m.t + ih, class: "marker-line" }), noteGlyph(a.kind, ax, m.t + 1, 4.5), s("rect", { x: ax - 8, y: m.t - 8, width: 16, height: 18, class: "hit" }));
      g.addEventListener("pointerenter", (e) => showTip(h("div", {}, h("div", { class: "tip-head" }, fmtDateTime(a.t)), noteTip(a)), e.clientX, e.clientY));
      g.addEventListener("pointerleave", hideTip);
      svg.append(g);
    }

    const cross = s("g", { visibility: "hidden", class: "cross" }, s("line", { x1: 0, x2: 0, y1: m.t, y2: m.t + ih, class: "cross-line" }));
    svg.append(cross);
    series.forEach((item) => {
      if (columns || item.muted) return dots.push(s("circle", { r: 0, visibility: "hidden" }));
      const dot = s("circle", { r: 4, fill: item.color, class: "dot dot-active", visibility: "hidden" });
      dots.push(dot);
      svg.append(dot);
    });

    const overlay = s("rect", { x: m.l, y: m.t, width: iw, height: ih, class: "overlay" });
    overlay.addEventListener("pointermove", (e) => {
      const box = svg.getBoundingClientRect();
      const index = nearestIndex(xs, e.clientX - box.left);
      if (index !== active) setActive(index);
      else if (index != null) showTip(tipContent(index), e.clientX, e.clientY);
    });
    overlay.addEventListener("pointerleave", () => setActive(null));
    svg.insertBefore(overlay, svg.querySelector(".marker"));

    geometry = { cross, dots, xs, ys, svg, top: m.t };
    queueMicrotask(() => active != null && host.matches(":focus-visible") && setActive(active));
    return svg;
  }

  host.addEventListener("focus", () => {
    if (active == null) active = times.length - 1;
    setActive(active);
  });
  host.addEventListener("blur", () => setActive(null));
  host.addEventListener("keydown", (e) => {
    const last = times.length - 1;
    const next = { ArrowLeft: Math.max(0, (active ?? last) - 1), ArrowRight: Math.min(last, (active ?? last) + 1), Home: 0, End: last }[e.key];
    if (e.key === "Escape") return setActive(null);
    if (next == null) return;
    e.preventDefault();
    setActive(next);
  });
  responsive(host, draw);
  return host;
}

/* --------------------------------------------------------- mini columnas */

/** Columnas diminutas sin ejes para una señal (p. ej. fallos por tramo); null = sin medir (trama). */
export function miniColumns(values, { color = "var(--c-error)", height = 36, label = "" } = {}) {
  const host = h("div", { class: "mini", role: "img", "aria-label": label });
  responsive(host, (width) => {
    const svg = s("svg", { class: "mini-plot", width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
    const hatch = hatchDefs(svg);
    const max = Math.max(1, ...values.filter((v) => v != null));
    const band = width / Math.max(1, values.length);
    const bw = Math.max(1, Math.min(6, band - 1));
    svg.append(s("line", { x1: 0, x2: width, y1: height - 0.5, y2: height - 0.5, class: "axis" }));
    values.forEach((v, i) => {
      const cx = i * band + band / 2;
      if (v == null) return svg.append(s("rect", { x: i * band, y: 0, width: band, height: height - 1, fill: hatch, class: "gap" }));
      if (!v) return;
      const hh = Math.max(2, ((height - 4) * v) / max);
      svg.append(s("rect", { x: cx - bw / 2, y: height - 1 - hh, width: bw, height: hh, rx: Math.min(1.5, bw / 2), fill: color, class: "bar" }));
    });
    return svg;
  });
  return host;
}

/* --------------------------------------------------------------- reparto */

/** Un todo repartido en partes, a lo ancho. Las cifras van fuera (en la lista que lo acompaña). */
export function shareStrip(parts, { ariaLabel, onSelect } = {}) {
  const total = parts.reduce((a, p) => a + (p.value || 0), 0);
  const strip = h("div", { class: "share", role: "img", "aria-label": ariaLabel || parts.map((p) => `${p.label}: ${fmtInt(p.value)}`).join(", ") });
  for (const p of parts) {
    if (!(p.value > 0)) continue;
    const seg = h("span", { class: "share-part", title: p.label });
    seg.style.setProperty("--w", `${(100 * p.value) / total}%`);
    seg.style.setProperty("--c", p.color);
    if (onSelect) seg.addEventListener("click", () => onSelect(p));
    strip.append(seg);
  }
  return strip;
}

/* ------------------------------------------------------------ comunidades */

/** Una marca por comunidad observada: las activas en color y el resto en contorno. Solo hasta ~600. */
export function unitGrid(total, active, { label } = {}) {
  const host = h("div", { class: "units", role: "img", "aria-label": label });
  responsive(host, (width) => {
    const cell = total > 300 ? 9 : 12;
    const cols = Math.max(10, Math.floor((width + 3) / cell));
    const rows = Math.ceil(total / cols);
    const svg = s("svg", { class: "units-plot", width, height: rows * cell, viewBox: `0 0 ${width} ${rows * cell}`, "aria-hidden": "true" });
    for (let i = 0; i < total; i++) {
      const cx = (i % cols) * cell + cell / 2 - 1;
      const cy = Math.floor(i / cols) * cell + cell / 2;
      svg.append(s("rect", { x: cx - cell / 2 + 2, y: cy - cell / 2 + 2, width: cell - 4, height: cell - 4, rx: 1.5, class: i < active ? "unit unit-on" : "unit" }));
    }
    return svg;
  });
  return host;
}

/* -------------------------------------------------------------- latencia */

const LAT_TICKS = [10, 100, 1000, 10000];

/**
 * Escala logarítmica de latencia por fila: punto = media; tramo = intervalo del histograma que contiene
 * el p95 (el backend da el límite superior de ese intervalo, no un percentil exacto).
 * rows: [{ label, mean, interval: [lo, hi|null], samples, small }]
 */
export function latencyScale(rows, { label } = {}) {
  const host = h("div", { class: "latency", role: "img", "aria-label": label });
  responsive(host, (width) => {
    const narrow = width < 520;
    const lw = narrow ? 0 : Math.min(170, Math.round(width * 0.28));
    const rh = narrow ? 44 : 30;
    const m = { l: lw + 8, r: 16, t: 22 };
    const iw = Math.max(80, width - m.l - m.r);
    const height = m.t + rows.length * rh + 6;
    const lx = (v) => m.l + ((Math.log10(Math.max(10, Math.min(60000, v))) - 1) / (Math.log10(60000) - 1)) * iw;
    const svg = s("svg", { class: "plot latency-plot", width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
    for (const t of LAT_TICKS) {
      svg.append(s("line", { x1: lx(t), x2: lx(t), y1: m.t - 4, y2: height - 4, class: "gl" }));
      svg.append(s("text", { x: lx(t), y: 12, class: "tick", "text-anchor": "middle" }, fmtMs(t)));
    }
    rows.forEach((r, i) => {
      const cy = m.t + i * rh + (narrow ? 30 : rh / 2);
      if (narrow) svg.append(s("text", { x: m.l, y: cy - 14, class: "lat-label" }, r.label));
      else svg.append(s("text", { x: lw, y: cy + 4, class: "lat-label", "text-anchor": "end" }, r.label));
      svg.append(s("line", { x1: m.l, x2: m.l + iw, y1: cy, y2: cy, class: "lat-rail" }));
      if (r.interval) {
        const [lo, hi] = r.interval;
        const x0 = lx(Math.max(10, lo || 10));
        const x1 = hi ? lx(hi) : m.l + iw;
        svg.append(s("rect", { x: x0, y: cy - 5, width: Math.max(3, x1 - x0), height: 10, rx: 2, class: hi ? "lat-p95" : "lat-p95 lat-open" }));
      }
      if (r.mean != null) svg.append(s("circle", { cx: lx(r.mean), cy, r: 4.5, class: r.small ? "lat-mean lat-small" : "lat-mean" }));
    });
    return svg;
  });
  return host;
}

/* --------------------------------------------------------------- versiones */

/** Carriles por versión sobre el eje del período. lanes: versionLanes(); colors: version -> color. */
export function versionTrack(lanes, { start, end, colors, running, annotations = [], label }) {
  const host = h("div", { class: "track", role: "img", "aria-label": label });
  responsive(host, (width) => {
    const lw = width < 520 ? 74 : 96;
    const rh = 30;
    const m = { l: lw, r: 12, t: 8, b: 24 };
    const iw = Math.max(80, width - m.l - m.r);
    const height = m.t + lanes.length * rh + m.b;
    const x = linear(start, end, m.l, m.l + iw);
    const svg = s("svg", { class: "plot track-plot", width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
    for (const tick of timeTicks(start, end - DAY, "day", Math.max(2, Math.floor(iw / 80)))) {
      svg.append(s("line", { x1: x(tick.t), x2: x(tick.t), y1: m.t, y2: height - m.b, class: "gl" }));
      svg.append(s("text", { x: x(tick.t), y: height - 8, class: "tick", "text-anchor": "middle" }, tick.label));
    }
    lanes.forEach((lane, i) => {
      const cy = m.t + i * rh + rh / 2;
      svg.append(s("text", { x: lw - 10, y: cy + 4, class: `track-label${lane.version === running ? " is-running" : ""}`, "text-anchor": "end" }, shortVersion(lane.version)));
      for (const sp of lane.spans) {
        const x0 = Math.max(m.l, x(sp.start));
        const x1 = Math.min(m.l + iw, x(sp.end + DAY));
        if (x1 <= x0) continue;
        const r = s("rect", { x: x0, y: cy - 7, width: Math.max(3, x1 - x0 - 1), height: 14, rx: 3, class: "track-span" });
        r.style.setProperty("--c", colors(lane.version));
        svg.append(r);
      }
    });
    for (const a of annotations) {
      if (a.t < start || a.t > end) continue;
      const row = lanes.findIndex((l) => l.version === a.version);
      const cy = row >= 0 ? m.t + row * rh + rh / 2 : m.t + 2;
      svg.append(noteGlyph(a.kind, x(a.t), cy, 5));
    }
    return svg;
  });
  return host;
}

/* ---------------------------------------------------------- regla del período */

/**
 * La firma de Studio: la ventana del período, lo medido en sólido, los huecos con trama y las
 * anotaciones como glifos. Se dibuja con HTML posicionado en % para que escale sin redibujar.
 */
export function periodRuler({ start, end, gaps, annotations = [] }) {
  const span = end - start;
  const pos = (t) => `${(100 * (Math.min(end, Math.max(start, t)) - start)) / span}%`;
  const track = h("span", { class: "ruler-track", "aria-hidden": "true" });
  for (const g of gaps) {
    const a = Math.max(start, g.start);
    const b = Math.min(end, g.end);
    if (b <= a) continue;
    const seg = h("span", { class: "ruler-gap" });
    seg.style.setProperty("--l", pos(a));
    seg.style.setProperty("--w", `${Math.max(0.5, (100 * (b - a)) / span)}%`);
    track.append(seg);
  }
  for (const a of annotations) {
    if (a.t < start || a.t > end) continue;
    const mark = h("span", { class: "ruler-note" }, noteIcon(a.kind));
    mark.style.setProperty("--l", pos(a.t));
    track.append(mark);
  }
  return track;
}

/* ------------------------------------------------------------- table views */

export function dataTable(head, rows, { caption, numeric } = {}) {
  const isNum = (i) => (numeric ? numeric.includes(i) : i > 0);
  return h("div", { class: "table-wrap" }, h("table", { class: "table" }, caption ? h("caption", { class: "sr-only" }, caption) : null,
    h("thead", {}, h("tr", {}, head.map((c, i) => h("th", { scope: "col", class: isNum(i) ? "num" : "" }, c)))),
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c, i) => (i ? h("td", { class: isNum(i) ? "num" : "" }, c) : h("th", { scope: "row" }, c))))))));
}

/** Tabla equivalente de una serie temporal, para quien no puede o no quiere usar el gráfico. */
export function seriesTable(times, step, series, yFormat = fmtInt) {
  const head = [step === "hour" ? "Hora (UTC)" : "Día (UTC)", ...series.map((i) => i.name)];
  const rows = times.map((t, i) => [step === "hour" ? fmtDateTime(t) : fmtDay(t), ...series.map((item) => (item.values[i] == null ? "Sin medición" : yFormat(item.values[i])))]);
  return dataTable(head, rows, { caption: "Valores del gráfico" });
}

export function legend(items) {
  return h("ul", { class: "legend" }, items.map((i) => h("li", {}, swatch(i.color, i.kind || "line"), h("span", {}, i.name))));
}

/** Tira de cobertura para el diálogo de detalle (igual que la regla, más alta). */
export function coverageStrip(coverage, startMs, endMs, { label } = {}) {
  const strip = h("div", { class: "cov-strip", role: "img", "aria-label": label });
  strip.append(periodRuler({ start: startMs, end: endMs, gaps: (coverage.gaps || []).map((g) => ({ start: Date.parse(g.start), end: Date.parse(g.end) })) }));
  return strip;
}
