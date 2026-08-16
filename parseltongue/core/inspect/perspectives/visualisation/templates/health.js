// ── Health view — full-page diagnostics over the page's side-car data ──
// A first-class view (peer of Source/Structure/Layers/Graph), driven by
// the global search bar. Reads HEALTH_DATA / COVERAGE_DATA / TAINT_DATA
// shipped with the page; no server round-trip.

function renderHealth() {
  const root = document.getElementById('health-root');
  if (!root) return;
  const hd = (typeof HEALTH_DATA !== 'undefined') ? HEALTH_DATA : {};
  const covAll = (typeof COVERAGE_DATA !== 'undefined') ? COVERAGE_DATA : [];
  const td = (typeof TAINT_DATA !== 'undefined') ? TAINT_DATA : {sources: [], tainted: [], reasons: {}};

  const allRows = [];
  Object.keys(hd).forEach(name => hd[name].forEach(f => allRows.push({name, ...f})));

  // Global search drives the view — same typed query as every other view.
  const q = (typeof searchQuery !== 'undefined') ? searchQuery : '';
  const diag = (typeof searchMode !== 'undefined') && searchMode === 'diagnostics';
  const rows = allRows.filter(r => {
    if (!q) return true;
    if (diag) return r.type.toLowerCase() === q || r.category.toLowerCase() === q;
    return `${r.name} ${r.category} ${r.type} ${r.detail || ''}`.toLowerCase().includes(q);
  });
  // Diagnostics queries are about findings — coverage stays unfiltered there.
  const cov = (diag || !q) ? covAll : covAll.filter(c => `${c.type} ${c.document || ''} ${c.text}`.toLowerCase().includes(q));

  const issues = rows.filter(r => r.category === 'issue');
  const warnings = rows.filter(r => r.category === 'warning');
  const loader = rows.filter(r => r.category === 'loader');
  const allIssues = allRows.filter(r => r.category === 'issue').length;
  const allLoader = allRows.filter(r => r.category === 'loader').length;
  const ok = allIssues === 0 && allLoader === 0;

  // Documents assembled from typed coverage rows.
  const docs = {};
  cov.forEach(c => {
    const key = c.document || `(${c.type})`;
    (docs[key] = docs[key] || []).push(c);
  });
  const quoteRows = covAll.filter(c => c.type === 'quote_range' && typeof c.fraction === 'number');
  const avgQuoted = quoteRows.length ? quoteRows.reduce((a, c) => a + c.fraction, 0) / quoteRows.length : null;

  let html = '';

  // ── Verdict banner — over ALL findings, never the filtered view ──
  html += `<div class="rounded-xl p-4 mb-4 font-bold ${ok ? 'bg-green/10 text-green' : 'bg-red/10 text-red'}">`;
  html += ok ? '&#x2713; Consistent' : `&#x2716; Inconsistent — ${allIssues} issue(s), ${allLoader} loader error(s)`;
  if (q) html += `<span class="ml-3 text-xs font-normal text-overlay0">filtered by "${esc(q)}" — ${rows.length}/${allRows.length} findings, ${cov.length}/${covAll.length} coverage rows</span>`;
  html += `</div>`;

  // ── Stat tiles ──
  const tile = (label, value, color) =>
    `<div class="bg-surface0 rounded-xl p-4"><div class="text-2xl font-bold ${color}">${value}</div><div class="text-xs text-overlay0 mt-1">${label}</div></div>`;
  html += `<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">`;
  html += tile('issues', allIssues, allIssues ? 'text-red' : 'text-green');
  html += tile('warnings', allRows.filter(r => r.category === 'warning').length, 'text-yellow');
  html += tile('loader errors', allLoader, allLoader ? 'text-red' : 'text-subtext');
  html += tile('taint sources', (td.sources || []).length, (td.sources || []).length ? 'text-red' : 'text-subtext');
  html += tile('tainted nodes', (td.tainted || []).length, (td.tainted || []).length ? 'text-yellow' : 'text-subtext');
  html += tile('documents', quoteRows.length, 'text-sky');
  html += `</div>`;

  // ── Coverage chart — quote coverage by document (magnitude → h-bars) ──
  if (quoteRows.length) {
    const claimsByDoc = {};
    covAll.forEach(c => {
      if (c.type === 'corpus_claim' && c.document) claimsByDoc[c.document] = c;
    });
    const sortedDocs = [...quoteRows].sort((a, b) => b.fraction - a.fraction);
    html += `<div class="bg-surface0 rounded-xl p-4 mb-4">`;
    html += `<div class="flex items-baseline justify-between mb-3">`;
    html += `<h3 class="text-xs font-bold text-overlay0">QUOTE COVERAGE BY DOCUMENT</h3>`;
    html += `<div><span class="text-2xl font-bold text-text">${Math.round((avgQuoted || 0) * 100)}%</span>`;
    html += `<span class="text-xs text-overlay0 ml-1">average</span></div></div>`;
    html += `<div class="space-y-1.5">`;
    sortedDocs.forEach(c => {
      const pct = Math.round(c.fraction * 100);
      const claim = claimsByDoc[c.document];
      html += `<div class="flex items-center gap-3 group rounded hover:bg-surface1 px-1 py-0.5" `;
      html += `title="${esc(c.text)}${claim ? ' — quantified by ' + esc(claim.claims ? claim.claims.join(', ') : claim.text) : ''}">`;
      html += `<span class="w-44 shrink-0 text-[11px] text-subtext truncate text-right">${esc(c.document)}</span>`;
      html += `<div class="flex-1 h-2 bg-crust rounded-[4px] overflow-hidden">`;
      html += `<div class="h-full rounded-r-[4px]" style="width:${Math.max(pct, 0.5)}%;background:var(--sky)"></div></div>`;
      html += `<span class="w-9 shrink-0 text-[11px] text-subtext tabular-nums">${pct}%</span>`;
      html += `<span class="w-16 shrink-0 text-[10px] ${claim ? 'text-mauve' : 'text-surface2'}">${claim ? '&#x2200; ' + (claim.claims ? claim.claims.length : 1) + ' claim' + ((claim.claims && claim.claims.length > 1) ? 's' : '') : ''}</span>`;
      html += `</div>`;
    });
    html += `</div>`;
    html += `<div class="text-[10px] text-overlay0 mt-2">bar = share of the document covered by verified quotes &middot; &#x2200; = document also under grounded corpus claims</div>`;
    html += `</div>`;
  }

  // ── Counts by finding type — click feeds the global search ──
  const byType = {};
  allRows.forEach(r => { byType[r.type] = (byType[r.type] || 0) + 1; });
  if (Object.keys(byType).length) {
    html += `<div class="flex flex-wrap gap-2 mb-6 text-[11px]">`;
    Object.keys(byType).sort().forEach(t => {
      const active = diag && q === t.toLowerCase();
      html += `<button data-htype="${esc(t)}" class="px-2 py-1 rounded-lg border ${active ? 'border-mauve text-mauve font-bold' : 'border-surface2 text-subtext hover:bg-surface1'}">${esc(t)} &times; ${byType[t]}</button>`;
    });
    html += `</div>`;
  }

  // ── Two columns: nodes | documents ──
  html += `<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">`;

  // Nodes column
  html += `<div><h3 class="text-sm font-bold text-lavender mb-2">Nodes</h3><div class="space-y-4">`;
  const section = (label, items, color, icon) => {
    if (!items.length) return;
    html += `<div><div class="text-overlay0 font-bold text-xs mb-1">${label} (${items.length})</div><div class="space-y-1">`;
    items.forEach(r => {
      const clickable = typeof ITEM_BY_ID !== 'undefined' && ITEM_BY_ID[r.name];
      html += `<div class="bg-surface0 rounded-lg p-3 text-xs ${clickable ? 'cursor-pointer hover:bg-surface1' : ''}"`;
      if (clickable) html += ` onclick="showDetail(ITEM_BY_ID['${r.name.replace(/'/g, "\\'")}'])"`;
      html += `><span class="${color} font-bold">${icon} ${esc(r.name)}</span>`;
      html += ` <span class="text-overlay0">${esc(r.type)}</span>`;
      if (r.detail) html += `<div class="text-subtext mt-1">${esc(r.detail)}</div>`;
      html += `</div>`;
    });
    html += `</div></div>`;
  };
  section('Issues', issues, 'text-red', '&#x2716;');
  section('Warnings', warnings, 'text-yellow', '&#x26a0;');
  section('Loader', loader, 'text-overlay0', '&#x2699;');
  if ((td.sources || []).length || (td.tainted || []).length) {
    html += `<div><div class="text-overlay0 font-bold text-xs mb-1">Taint</div>`;
    html += `<div class="bg-surface0 rounded-lg p-3 text-xs text-subtext">${(td.sources || []).length} source(s) &rarr; ${(td.tainted || []).length} tainted node(s)`;
    (td.sources || []).slice(0, 10).forEach(nm => {
      html += `<div class="text-red mt-1">&#x2716; ${esc(nm)}${(td.reasons || {})[nm] ? ` <span class="text-overlay0">${esc(td.reasons[nm])}</span>` : ''}</div>`;
    });
    html += `</div></div>`;
  }
  if (!rows.length) html += `<div class="text-xs text-overlay0">${q ? 'No findings match the search.' : 'No findings — all clear.'}</div>`;
  html += `</div></div>`;

  // Documents column
  html += `<div><h3 class="text-sm font-bold text-lavender mb-2">Documents</h3><div class="space-y-2">`;
  Object.keys(docs).sort().forEach(doc => {
    html += `<div class="bg-surface0 rounded-lg p-3 text-xs">`;
    html += `<div class="font-bold text-sky mb-1">${esc(doc)}</div>`;
    docs[doc].forEach(c => {
      if (c.type === 'quote_range' && typeof c.fraction === 'number') {
        const pct = Math.round(c.fraction * 100);
        html += `<div class="flex items-center gap-2 mt-1" title="${esc(c.text)}">`;
        html += `<div class="flex-1 h-1.5 bg-crust rounded-[4px] overflow-hidden"><div class="h-full rounded-r-[4px]" style="width:${Math.max(pct, 0.5)}%;background:var(--sky)"></div></div>`;
        html += `<span class="text-subtext shrink-0 tabular-nums">${pct}% quoted</span></div>`;
      } else if (c.type === 'corpus_claim' && Array.isArray(c.claims)) {
        html += `<div class="flex flex-wrap gap-1 mt-1.5">`;
        c.claims.forEach(nm => {
          const clickable = typeof ITEM_BY_ID !== 'undefined' && ITEM_BY_ID[nm];
          html += `<button class="px-1.5 py-0.5 rounded border border-mauve/40 text-mauve text-[10px] ${clickable ? 'hover:bg-surface1' : ''}"`;
          if (clickable) html += ` onclick="showDetail(ITEM_BY_ID['${nm.replace(/'/g, "\\'")}'])"`;
          html += `>&#x2200; ${esc(nm)}</button>`;
        });
        html += `</div>`;
      } else {
        html += `<div class="text-subtext mt-1"><span class="text-overlay0">[${esc(c.type)}]</span> ${esc(c.text)}</div>`;
      }
    });
    html += `</div>`;
  });
  if (!Object.keys(docs).length) html += `<div class="text-xs text-overlay0">${q ? 'No coverage rows match the search.' : 'No coverage data.'}</div>`;
  html += `</div></div>`;

  html += `</div>`;
  root.innerHTML = html;

  // Type chips feed the global search bar — one search, every view.
  root.querySelectorAll('[data-htype]').forEach(btn => {
    btn.onclick = () => {
      const t = btn.getAttribute('data-htype');
      const searchBox = document.getElementById('search');
      const active = searchMode === 'diagnostics' && searchQuery === t.toLowerCase();
      const next = active ? '' : 'diag:' + t;
      if (searchBox) searchBox.value = next;
      parseSearch(next);
      render();
      renderHealth();
    };
  });
}
