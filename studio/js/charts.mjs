// Gráficos SVG/HTML sin dependencias. Especificaciones de marcas: líneas de 2 px, columnas de
// hasta 24 px con el extremo de datos redondeado, 2 px de separación entre segmentos, rejilla
// hairline sólida y texto siempre en los tonos de texto (nunca en el color de la serie).
import { clear, h, s, uid } from "./dom.mjs";
import { fmtCompact, fmtDateTime, fmtDay, fmtDuration, fmtInt, fmtPct } from "./format.mjs";
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
  let left = clientX + 14;
  if (left + width > window.innerWidth - margin) left = clientX - width - 14;
  const top = Math.min(Math.max(margin, clientY - height / 2), window.innerHeight - height - margin);
  node.style.setProperty("left", `${Math.max(margin, left)}px`);
  node.style.setProperty("top", `${top}px`);
}

export function hideTip() {
  tooltipNode().hidden = true;
}

function swatch(color, kind = "line") {
  const key = h("span", { class: `key key-${kind}`, "aria-hidden": "true" });
  key.style.setProperty("--c", color);
  return key;
}

/** Fila de tooltip: el valor manda, el nombre acompaña; la clave es un trazo corto, no una caja. */
function tipRow(color, value, name, kind) {
  return h("div", { class: "tip-row" }, swatch(color, kind), h("strong", {}, value), h("span", { class: "tip-name" }, name));
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

/* -------------------------------------------------------------- time charts */

/**
 * Serie temporal. kind "line" (áreas/líneas) o "columns" (apiladas; side -1 dibuja bajo el cero).
 * series: [{ key, name, values, color, area?, muted?, side? }]. Un valor null es "no medido".
 */
export function timeChart(o) {
  const {
    times, step, series, kind = "line", yFormat = fmtInt, gaps = [], annotations = [],
    height = 232, label, integer = true, zero = true, window = null,
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
  const host = h("div", { class: "chart", tabindex: "0", role: "group", "aria-roledescription": "gráfico", "aria-label": label });
  let active = null;
  let geometry = null;

  function bucketLabel(i) {
    return step === "hour" ? fmtDateTime(times[i]) : fmtDay(times[i]);
  }

  function tipContent(i) {
    const rows = [];
    for (const item of series) {
      const v = item.values[i];
      rows.push(v == null
        ? tipRow(item.color, "Sin medición", item.name, kind === "columns" ? "box" : "line")
        : tipRow(item.color, item.side === -1 ? `−${yFormat(v)}` : yFormat(v), item.name, kind === "columns" ? "box" : "line"));
    }
    const inGap = gaps.some((g) => g.start <= times[i] && g.end >= times[i] + size);
    const part = share(i) < 0.999
      ? h("div", { class: "tip-note" }, `${isPartial(i) ? "Tramo parcial" : "Medido"}: ${fmtDuration((share(i) * size) / 1000)} de ${fmtDuration(size / 1000)}`)
      : null;
    const notes = annotations
      .filter((a) => a.t >= times[i] && a.t < times[i] + size)
      .map((a) => h("div", { class: "tip-note" }, "◆ ", a.title, a.version ? ` · ${a.version}` : ""));
    return h("div", {}, h("div", { class: "tip-head" }, bucketLabel(i)), rows, inGap ? h("div", { class: "tip-note" }, "Sin cobertura en este tramo") : null, part, notes);
  }

  function setActive(index, announce = true) {
    active = index;
    if (!geometry) return;
    const { cross, dots, xs, svg, ys } = geometry;
    if (index == null) {
      cross.setAttribute("visibility", "hidden");
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
      showTip(tipContent(index), box.left + x, box.top + geometry.top + 20);
    }
  }

  function draw(width) {
    const m = { l: 48, r: 14, t: 10, b: 30 };
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
    const hatch = uid("hatch");
    svg.append(
      s("defs", {}, s("pattern", { id: hatch, width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, s("line", { x1: 0, y1: 0, x2: 0, y2: 6, class: "hatch-line" }))),
    );

    for (const v of scale.ticks) {
      svg.append(s("line", { x1: m.l, x2: m.l + iw, y1: y(v), y2: y(v), class: v === 0 && zero ? "axis" : "gl" }));
      svg.append(s("text", { x: m.l - 8, y: y(v) + 4, class: "tick", "text-anchor": "end" }, fmtCompact(v)));
    }
    for (const g of gaps) {
      const from = Math.max(t0, g.start);
      const to = Math.min(columns ? t1 : times.at(-1), g.end);
      if (to > from) svg.append(s("rect", { x: x(from), y: m.t, width: Math.max(2, x(to) - x(from)), height: ih, fill: `url(#${hatch})`, class: "gap" }));
    }
    const stepTicks = timeTicks(t0, columns ? t1 - size : t1, step, Math.max(2, Math.floor(iw / 72)));
    for (const tick of stepTicks) {
      const tx = columns ? x(tick.t) + band / 2 : x(tick.t);
      svg.append(s("text", { x: tx, y: height - 8, class: tick.major ? "tick tick-major" : "tick", "text-anchor": "middle" }, tick.label));
    }

    const ys = series.map(() => times.map(() => null));
    const dots = [];
    if (columns) {
      const bw = Math.min(24, Math.max(3, band - 4));
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
              // 2 px de superficie entre segmentos apilados
              if (sign === 1) hgt = Math.max(1, hgt - 2);
              else top += 2, hgt = Math.max(1, hgt - 2);
            }
            const px = xs[i] - bw / 2;
            const d = last ? roundedBar(px, top, bw, hgt, 4, sign === 1) : `M${px} ${top}h${bw}v${hgt}h${-bw}Z`;
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
          if (item.area && seg.length > 1) svg.append(s("path", { d: areaPath(seg, y(0)), fill: item.color, class: "area" }));
          if (seg.length > 1) svg.append(s("path", { d: linePath(seg), stroke: item.color, class: item.muted ? "line line-muted" : "line" }));
          else svg.append(s("circle", { cx: seg[0][0], cy: seg[0][1], r: 3.5, fill: item.color, class: "dot" }));
        }
        // Un tramo parcial no es una caída: se une con trazo discontinuo y se marca con un punto hueco.
        for (let i = 0; i < ypx.length; i++) {
          if (!part(i) || ypx[i] == null) continue;
          for (const j of [i - 1, i + 1]) {
            if (j < 0 || j >= ypx.length || ypx[j] == null || (part(j) && j > i)) continue;
            svg.append(s("path", { d: linePath([[xs[i], ypx[i]], [xs[j], ypx[j]]]), stroke: item.color, class: "line line-partial" }));
          }
          if (!item.muted) svg.append(s("circle", { cx: xs[i], cy: ypx[i], r: 4, class: "dot dot-hollow", stroke: item.color }));
        }
        if (!item.muted) {
          const lastI = item.values.findLastIndex((v, i) => v != null && !part(i));
          if (lastI >= 0) svg.append(s("circle", { cx: xs[lastI], cy: ypx[lastI], r: 4, fill: item.color, class: "dot" }));
        }
      });
    }

    // Marcadores de actualizaciones sobre el eje.
    for (const a of annotations) {
      if (a.t < t0 || a.t > t1) continue;
      const ax = x(a.t);
      const base = m.t + ih;
      const g = s("g", { class: "marker" }, s("line", { x1: ax, x2: ax, y1: m.t, y2: base, class: "marker-line" }), s("path", { d: `M${ax - 5} ${base}L${ax} ${base - 5}L${ax + 5} ${base}L${ax} ${base + 5}Z`, class: "marker-diamond" }), s("circle", { cx: ax, cy: base, r: 12, class: "hit" }));
      g.addEventListener("pointerenter", (e) => showTip(h("div", {}, h("div", { class: "tip-head" }, fmtDateTime(a.t)), h("div", { class: "tip-note" }, "◆ ", a.title, a.version ? ` · ${a.version}` : "")), e.clientX, e.clientY));
      g.addEventListener("pointerleave", hideTip);
      svg.append(g);
    }

    const cross = s("g", { visibility: "hidden", class: "cross" }, s("line", { x1: 0, x2: 0, y1: m.t, y2: m.t + ih, class: "cross-line" }));
    svg.append(cross);
    if (!columns)
      series.forEach((item) => {
        if (item.muted) { dots.push(s("circle", { r: 0, visibility: "hidden" })); return; }
        const dot = s("circle", { r: 4.5, fill: item.color, class: "dot", visibility: "hidden" });
        dots.push(dot);
        svg.append(dot);
      });
    else series.forEach(() => dots.push(s("circle", { r: 0, visibility: "hidden" })));

    const overlay = s("rect", { x: m.l, y: m.t, width: iw, height: ih, class: "overlay" });
    overlay.addEventListener("pointermove", (e) => {
      const box = svg.getBoundingClientRect();
      const index = nearestIndex(xs, e.clientX - box.left);
      if (index !== active) setActive(index);
      else if (index != null) showTip(tipContent(index), e.clientX, e.clientY);
    });
    overlay.addEventListener("pointerleave", () => setActive(null));
    svg.append(overlay);

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

/* ---------------------------------------------------------------- sparkline */

export function sparkline(values, { color = "var(--series-1)", width = 112, height = 32, label = "" } = {}) {
  const svg = s("svg", { class: "spark", width, height, viewBox: `0 0 ${width} ${height}`, role: label ? "img" : "presentation", "aria-label": label || null, "aria-hidden": label ? null : "true" });
  const real = values.filter((v) => v != null);
  if (real.length < 2) return svg;
  const max = Math.max(...real, 1);
  const x = linear(0, values.length - 1, 4, width - 6);
  const y = linear(0, max, height - 4, 4);
  const xs = values.map((_, i) => x(i));
  const ys = values.map((v) => (v == null ? null : y(v)));
  for (const seg of segments(xs, ys)) if (seg.length > 1) svg.append(s("path", { d: linePath(seg), stroke: color, class: "line spark-line" }));
  const lastI = values.findLastIndex((v) => v != null);
  svg.append(s("circle", { cx: xs[lastI], cy: ys[lastI], r: 3, fill: color, class: "dot" }));
  return svg;
}

/* ------------------------------------------------------------- ranked bars */

/** Barras horizontales de un solo tono ordenadas de mayor a menor. rows: [{ label, hint, value, text }]. */
export function rankedBars(rows, { max } = {}) {
  const top = max ?? Math.max(1, ...rows.map((r) => r.value));
  return h("ol", { class: "ranked" }, rows.map((r) => {
    const track = h("span", { class: "track" }, h("span", { class: "fill" }));
    track.firstChild.style.setProperty("--w", `${Math.max(r.value > 0 ? 1.5 : 0, (100 * r.value) / top)}%`);
    return h("li", {}, h("span", { class: "rb-label" }, r.label, r.hint ? h("small", {}, r.hint) : null), track, h("strong", { class: "rb-value" }, r.text ?? fmtInt(r.value)));
  }));
}

/* ----------------------------------------------------------- segmented bar */

/** Un todo repartido en partes. Delgada y sin texto: las cifras van en la leyenda de al lado. */
export function segmentedBar(parts, { total, ariaLabel } = {}) {
  const sum = total ?? parts.reduce((a, p) => a + p.value, 0);
  const bar = h("div", { class: "segbar", role: "img", "aria-label": ariaLabel || parts.map((p) => `${p.label}: ${fmtInt(p.value)}`).join(", ") });
  for (const p of parts) {
    if (!(p.value > 0)) continue;
    const seg = h("span", { class: "seg-part" });
    seg.style.setProperty("--w", `${(100 * p.value) / sum}%`);
    seg.style.setProperty("--c", p.color);
    bar.append(seg);
  }
  const legend = h("ul", { class: "legend legend-figures" }, parts.map((p) => {
    const item = h("li", {}, swatch(p.color, "box"), h("span", { class: "lg-name" }, p.label), h("strong", {}, fmtInt(p.value)), h("span", { class: "lg-pct" }, sum ? fmtPct((100 * p.value) / sum, p.value / sum < 0.1 ? 1 : 0) : "—"));
    if (p.note) item.title = p.note;
    return item;
  }));
  return h("div", { class: "segmented" }, bar, legend);
}

/* ---------------------------------------------------------------- legends */

export function legend(items) {
  return h("ul", { class: "legend" }, items.map((i) => h("li", {}, swatch(i.color, i.kind || "line"), h("span", {}, i.name))));
}

/* ----------------------------------------------------------- coverage strip */

/** Línea de tiempo del período: lo medido en sólido y cada hueco rayado, con su duración en el título. */
export function coverageStrip(coverage, startMs, endMs, { label } = {}) {
  const span = endMs - startMs;
  const strip = h("div", { class: "cov-strip", role: "img", "aria-label": label });
  for (const g of coverage.gaps) {
    const a = Math.max(startMs, Date.parse(g.start));
    const b = Math.min(endMs, Date.parse(g.end));
    if (b <= a) continue;
    const seg = h("span", { class: "cov-gap", title: `Sin captura ${fmtDateTime(a)} → ${fmtDateTime(b)}` });
    seg.style.setProperty("--l", `${(100 * (a - startMs)) / span}%`);
    seg.style.setProperty("--w", `${Math.max(0.4, (100 * (b - a)) / span)}%`);
    strip.append(seg);
  }
  return strip;
}

/* ------------------------------------------------------------- table views */

export function dataTable(head, rows, { caption } = {}) {
  return h("div", { class: "table-wrap" }, h("table", { class: "table" }, caption ? h("caption", { class: "sr-only" }, caption) : null, h("thead", {}, h("tr", {}, head.map((c, i) => h("th", { scope: "col", class: i ? "num" : "" }, c)))), h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c, i) => (i ? h("td", { class: "num" }, c) : h("th", { scope: "row" }, c))))))));
}

/** Tabla equivalente de una serie temporal, para quien no puede o no quiere usar el gráfico. */
export function seriesTable(times, step, series, yFormat = fmtInt) {
  const head = [step === "hour" ? "Hora (UTC)" : "Día (UTC)", ...series.map((i) => i.name)];
  const rows = times.map((t, i) => [step === "hour" ? fmtDateTime(t) : fmtDay(t), ...series.map((item) => (item.values[i] == null ? "Sin medición" : yFormat(item.values[i])))]);
  return dataTable(head, rows, { caption: "Valores del gráfico" });
}
