// Construcción de DOM sin innerHTML: todo texto entra por nodos de texto.
const SVG = "http://www.w3.org/2000/svg";

function apply(node, props) {
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") node.setAttribute("class", value);
    else if (key.startsWith("on") && typeof value === "function")
      node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function h(tag, props, ...children) {
  const node = document.createElement(tag);
  apply(node, props);
  append(node, children);
  return node;
}

export function s(tag, props, ...children) {
  const node = document.createElementNS(SVG, tag);
  apply(node, props);
  append(node, children);
  return node;
}

export function clear(node, ...children) {
  node.replaceChildren();
  append(node, children);
  return node;
}

let counter = 0;
export const uid = (prefix = "id") => `${prefix}-${++counter}`;
