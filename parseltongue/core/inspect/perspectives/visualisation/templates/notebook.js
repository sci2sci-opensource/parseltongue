// ── Notebook view JS ──
// Depends on: core.js (kindDot, kindText, ITEM_BY_ID, switchView, showDetail)

// ── Footnote clicks → highlight margin pill + open detail ──
document.querySelectorAll('.nb-fn[data-node]').forEach(el => {
  el.addEventListener('click', (e) => {
    e.preventDefault();
    const nodeId = el.dataset.node;
    const fnNum = el.dataset.fn;
    const item = ITEM_BY_ID[nodeId];

    // Clear previous highlights
    document.querySelectorAll('.nb-margin-pill.nb-pill-active').forEach(p =>
      p.classList.remove('nb-pill-active'));

    // Find and highlight corresponding margin pill
    const row = el.closest('.nb-prose-row');
    if (row) {
      const pill = row.querySelector(`.nb-margin-pill[data-node="${nodeId}"]`);
      if (pill) pill.classList.add('nb-pill-active');
    }

    // Open detail sidebar
    if (item && typeof showDetail === 'function') showDetail(item);
  });
});

// ── Margin pill clicks → highlight self + open detail ──
document.querySelectorAll('.nb-margin-pill[data-node]').forEach(el => {
  el.addEventListener('click', (e) => {
    e.preventDefault();
    const nodeId = el.dataset.node;
    const item = ITEM_BY_ID[nodeId];

    // Clear previous highlights
    document.querySelectorAll('.nb-margin-pill.nb-pill-active').forEach(p =>
      p.classList.remove('nb-pill-active'));
    el.classList.add('nb-pill-active');

    // Open detail sidebar
    if (item && typeof showDetail === 'function') showDetail(item);
  });
});

// ── Footnote list row clicks ──
document.querySelectorAll('.nb-fn-row[data-node]').forEach(el => {
  el.addEventListener('click', (e) => {
    e.preventDefault();
    const nodeId = el.dataset.node;
    const item = ITEM_BY_ID[nodeId];

    document.querySelectorAll('.nb-margin-pill.nb-pill-active').forEach(p =>
      p.classList.remove('nb-pill-active'));

    const row = el.closest('.nb-prose-row');
    if (row) {
      const pill = row.querySelector(`.nb-margin-pill[data-node="${nodeId}"]`);
      if (pill) pill.classList.add('nb-pill-active');
    }

    if (item && typeof showDetail === 'function') showDetail(item);
  });
});

// ── Legacy node-ref clicks (if any remain) ──
document.querySelectorAll('.node-ref[data-node]').forEach(el => {
  el.addEventListener('click', (e) => {
    e.preventDefault();
    const name = el.dataset.node;
    const item = ITEM_BY_ID[name];
    if (item && typeof showDetail === 'function') showDetail(item);
  });
});

// ── pltg block toggle (expand/collapse code) ──
document.querySelectorAll('.nb-block-header').forEach(el => {
  el.addEventListener('click', () => {
    const code = el.parentElement.querySelector('.nb-block-code');
    if (code) code.classList.toggle('hidden');
    const arrow = el.querySelector('.nb-arrow');
    if (arrow) arrow.textContent = code && code.classList.contains('hidden') ? '\u25B6' : '\u25BC';
  });
});

// ── Node pill clicks in block summaries ──
document.querySelectorAll('.nb-node-pill[data-node]').forEach(el => {
  el.addEventListener('click', (e) => {
    e.preventDefault();
    const name = el.dataset.node;
    const item = ITEM_BY_ID[name];
    if (item && typeof showDetail === 'function') showDetail(item);
  });
});
