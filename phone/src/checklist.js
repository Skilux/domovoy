export function questionLabel(item) {
  if (item.endsWith('?')) return item;
  const text = item.replace(/_/g, ' ');
  return `${text[0].toUpperCase()}${text.slice(1)}?`;
}

export function renderChecklist(el, items) {
  el.textContent = '';
  el.hidden = !items.length;
  for (const item of items) {
    const row = document.createElement('li');
    row.textContent = questionLabel(item);
    el.append(row);
  }
}

export function tickQuestion(el, number) {
  const row = el.children[Number(number) - 1];
  if (row) row.classList.add('done');
}
