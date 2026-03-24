// ── Source View: document lines, evidence, quotes ──
let sourceInitialized = false;

function renderSource() {
  const container = document.getElementById('source-container');
  const items = filtered(DATA);
  document.getElementById('count').textContent = `${items.length} / ${DATA.length}`;
  container.innerHTML = '';

  if (FORM_TYPE === 'sr') {
    renderSrSource(container, items);
  } else if (FORM_TYPE === 'ln') {
    renderLnSource(container, items);
  } else if (FORM_TYPE === 'dx') {
    renderDxSource(container, items);
  } else if (FORM_TYPE === 'hn') {
    renderHnSource(container, items);
  }
}

function renderSrSource(container, items) {
  // Group by document
  const byDoc = {};
  items.forEach(d => {
    const doc = d.doc || '(unknown)';
    if (!byDoc[doc]) byDoc[doc] = [];
    byDoc[doc].push(d);
  });

  // Sort documents by number of matches (most first)
  const docs = Object.keys(byDoc).sort((a, b) => byDoc[b].length - byDoc[a].length);

  docs.forEach(doc => {
    const lines = byDoc[doc].sort((a, b) => (parseInt(a.line) || 0) - (parseInt(b.line) || 0));
    const section = document.createElement('div');
    section.className = 'mb-6';

    // Document header
    const header = document.createElement('div');
    header.className = 'flex items-center gap-2 mb-2 cursor-pointer select-none group';
    header.innerHTML = `
      <span class="text-xs text-overlay0 group-hover:text-text transition-colors">&#9660;</span>
      <span class="text-sm font-bold text-sky">${esc(doc)}</span>
      <span class="text-xs text-overlay0">${lines.length} matches</span>
    `;
    let collapsed = false;
    const body = document.createElement('div');
    body.className = 'bg-crust rounded-lg border border-surface1 overflow-hidden';

    header.onclick = () => {
      collapsed = !collapsed;
      body.classList.toggle('hidden', collapsed);
      header.querySelector('span').textContent = collapsed ? '\u25b6' : '\u25bc';
    };

    lines.forEach((d, i) => {
      const row = document.createElement('div');
      row.className = 'flex items-start gap-3 px-4 py-2 hover:bg-surface0/50 cursor-pointer transition-colors' +
        (i < lines.length - 1 ? ' border-b border-surface0' : '');
      row.onclick = () => showDetail(d);

      // Line number
      const lineNum = document.createElement('span');
      lineNum.className = 'text-overlay0 text-xs w-10 text-right shrink-0 select-none pt-0.5';
      lineNum.textContent = d.line;

      // Context (the actual source line)
      const ctx = document.createElement('div');
      ctx.className = 'flex-1 min-w-0';
      const codeLine = document.createElement('div');
      codeLine.className = 'text-xs text-text whitespace-pre-wrap break-all';
      codeLine.textContent = d.ctx || '';
      ctx.appendChild(codeLine);

      // Callers (pltg nodes that reference this line)
      if (d.callers && d.callers.length) {
        const callersDiv = document.createElement('div');
        callersDiv.className = 'flex flex-wrap gap-1 mt-1';
        d.callers.forEach(c => {
          const tag = document.createElement('span');
          const name = typeof c === 'object' ? c.name : c;
          const overlap = typeof c === 'object' ? c.overlap : null;
          const short = name.includes('.') ? name.split('.').slice(1).join('.') : name;
          tag.className = 'px-1.5 py-0.5 rounded text-[10px] bg-surface0 text-lavender';
          tag.textContent = short + (overlap != null ? ` ${Math.round(overlap * 100)}%` : '');
          tag.title = name;
          callersDiv.appendChild(tag);
        });
        ctx.appendChild(callersDiv);
      }

      row.appendChild(lineNum);
      row.appendChild(ctx);
      body.appendChild(row);
    });

    section.appendChild(header);
    section.appendChild(body);
    container.appendChild(section);
  });
}

function renderLnSource(container, items) {
  // Show evidence/origin quotes grouped by source document
  const withEvidence = items.filter(d => d.evidence && d.evidence.length > 0);
  if (!withEvidence.length) {
    container.innerHTML = '<div class="text-overlay0 text-sm p-4">No source evidence in current items.</div>';
    return;
  }

  // Group by evidence document
  const byDoc = {};
  withEvidence.forEach(d => {
    d.evidence.forEach(ev => {
      const doc = ev.doc || '(derived)';
      if (!byDoc[doc]) byDoc[doc] = [];
      byDoc[doc].push({ item: d, ev: ev });
    });
  });

  const docs = Object.keys(byDoc).sort();
  docs.forEach(doc => {
    const entries = byDoc[doc];
    const section = document.createElement('div');
    section.className = 'mb-6';

    const header = document.createElement('div');
    header.className = 'flex items-center gap-2 mb-2';
    header.innerHTML = `
      <span class="text-sm font-bold text-sky">${esc(doc)}</span>
      <span class="text-xs text-overlay0">${entries.length} references</span>
    `;

    const body = document.createElement('div');
    body.className = 'bg-crust rounded-lg border border-surface1 overflow-hidden';

    entries.forEach((e, i) => {
      const row = document.createElement('div');
      row.className = 'px-4 py-2' + (i < entries.length - 1 ? ' border-b border-surface0' : '');
      row.onclick = () => showDetail(e.item);
      row.style.cursor = 'pointer';

      // Node name + status
      const nameDiv = document.createElement('div');
      nameDiv.className = 'flex items-center gap-2 mb-1';
      const st = e.ev.status || (e.ev.verified ? 'verified' : 'unverified');
      const stColor = st === 'verified' ? 'text-green' : st === 'derived' ? 'text-blue' : 'text-yellow';
      const stIcon = st === 'verified' ? '\u2713' : st === 'derived' ? '\u2713' : '\u25cb';
      nameDiv.innerHTML = `
        <span class="${stColor} text-xs">${stIcon}</span>
        <span class="text-xs font-bold text-lavender">${esc(e.item.id)}</span>
        <span class="text-[10px] ${kindText(e.item.kind)}">${esc(e.item.kind)}</span>
      `;
      row.appendChild(nameDiv);

      // Quotes
      if (e.ev.quotes && e.ev.quotes.length) {
        e.ev.quotes.forEach(q => {
          const quoteDiv = document.createElement('div');
          const bc = st === 'verified' ? 'border-green' : 'border-yellow';
          quoteDiv.className = `text-xs text-subtext whitespace-pre-wrap bg-surface0 rounded p-2 mt-1 border-l-2 ${bc}`;
          quoteDiv.textContent = q;
          row.appendChild(quoteDiv);
        });
      }
      body.appendChild(row);
    });

    section.appendChild(header);
    section.appendChild(body);
    container.appendChild(section);
  });
}

function renderDxSource(container, items) {
  // Group diagnostics by category
  const byCat = {};
  items.forEach(d => {
    const cat = d.category || 'unknown';
    if (!byCat[cat]) byCat[cat] = [];
    byCat[cat].push(d);
  });

  Object.keys(byCat).sort().forEach(cat => {
    const section = document.createElement('div');
    section.className = 'mb-6';
    section.innerHTML = `<div class="flex items-center gap-2 mb-2">
      <span class="text-sm font-bold text-red">${esc(cat)}</span>
      <span class="text-xs text-overlay0">${byCat[cat].length}</span>
    </div>`;

    const body = document.createElement('div');
    body.className = 'bg-crust rounded-lg border border-surface1 overflow-hidden';
    byCat[cat].forEach((d, i) => {
      const row = document.createElement('div');
      row.className = 'px-4 py-2 cursor-pointer hover:bg-surface0/50' + (i < byCat[cat].length - 1 ? ' border-b border-surface0' : '');
      row.onclick = () => showDetail(d);
      row.innerHTML = `
        <div class="text-xs font-bold text-text">${esc(d.id)}</div>
        ${d.detail ? `<div class="text-xs text-subtext mt-1">${esc(d.detail)}</div>` : ''}
        <div class="text-[10px] text-overlay0 mt-1">${esc(d.kind)} / ${esc(d.type)}</div>
      `;
      body.appendChild(row);
    });
    section.appendChild(body);
    container.appendChild(section);
  });
}

function renderHnSource(container, items) {
  items.forEach(d => {
    const card = document.createElement('div');
    card.className = 'mb-4 bg-crust rounded-lg border border-surface1 p-4 cursor-pointer hover:border-teal/50';
    card.onclick = () => showDetail(d);

    const lenses = d.lenses || [];
    const present = lenses.filter(l => l != null);
    const diverges = present.length > 1 && present.some(l => l.value !== present[0].value || l.kind !== present[0].kind);

    let lensHtml = '';
    lenses.forEach((lens, i) => {
      lensHtml += `<div class="mt-2 pt-2 border-t border-surface0">`;
      lensHtml += `<span class="text-[10px] text-overlay0 font-bold">Lens ${i}</span>`;
      if (lens == null) {
        lensHtml += `<span class="text-[10px] text-overlay0 ml-2 italic">(absent)</span>`;
      } else {
        if (lens.kind) lensHtml += `<span class="ml-2 px-1 py-0.5 rounded text-[10px] ${kindColor(lens.kind)} text-crust">${esc(lens.kind)}</span>`;
        if (lens.value) lensHtml += `<div class="text-xs text-subtext mt-1">${esc(lens.value)}</div>`;
      }
      lensHtml += `</div>`;
    });

    card.innerHTML = `
      <div class="flex items-center gap-2 mb-1">
        <span class="text-sm font-bold text-teal">${esc(d.id)}</span>
        ${d.kind ? `<span class="px-1.5 py-0.5 rounded text-[10px] bg-teal text-crust">${esc(d.kind)}</span>` : ''}
        ${diverges ? '<span class="text-[10px] text-yellow">divergent</span>' : ''}
      </div>
      ${lensHtml}
    `;
    container.appendChild(card);
  });
}
