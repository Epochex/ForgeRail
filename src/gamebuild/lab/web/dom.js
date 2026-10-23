export const $ = id => document.getElementById(id);
export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
export function replace(id, ...nodes) { $(id).replaceChildren(...nodes); }
export function empty(message) { return el('p', 'empty', message); }
export function detail(label, content, className = '') {
  const node = el('details', className);
  node.append(el('summary', '', label), el('pre', '', content));
  return node;
}
export function option(value, text) { const node = el('option', '', text); node.value = value; return node; }
export function setOptions(select, options, selected) {
  const signature = JSON.stringify(options);
  if (select.dataset.options !== signature) {
    select.replaceChildren(...options.map(([v, label]) => option(v, label)));
    select.dataset.options = signature;
  }
  select.value = selected;
}
