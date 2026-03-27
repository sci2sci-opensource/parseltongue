// ── Structure render ──
function render() {
  const items = filtered(STRUCTURE_DATA);
  document.getElementById('count').textContent = `${items.length} / ${STRUCTURE_DATA.length}`;
  const container = document.getElementById('modules-container');
  container.innerHTML = '';

  // Group by module
  const groups = {};
  items.forEach(d => {
    const m = d.module || '(ungrouped)';
    if (!groups[m]) groups[m] = [];
    groups[m].push(d);
  });

  const sortedModules = Object.keys(groups).sort();
  sortedModules.forEach(mod => {
    const section = document.createElement('div');
    section.className = 'mb-6';

    const header = document.createElement('div');
    header.className = 'flex items-center gap-2 mb-2 cursor-pointer select-none group';
    header.innerHTML = `
      <span class="text-xs text-overlay0 group-hover:text-text transition-colors">&#9660;</span>
      <span class="text-sm font-bold text-lavender">${esc(mod)}</span>
      <span class="text-xs text-overlay0">${groups[mod].length}</span>
    `;
    let collapsed = false;
    const grid = document.createElement('div');
    grid.className = 'grid gap-2 grid-cols-[repeat(auto-fill,minmax(340px,1fr))]';

    header.onclick = () => {
      collapsed = !collapsed;
      grid.classList.toggle('hidden', collapsed);
      header.querySelector('span').textContent = collapsed ? '\u25b6' : '\u25bc';
    };

    groups[mod].forEach(d => {
      const card = document.createElement('div');
      const _td = (typeof TAINT_DATA !== 'undefined') ? TAINT_DATA : {sources:[], tainted:[], reasons:{}};
      const _tSrc = new Set(_td.sources);
      const _tAll = new Set(_td.tainted);
      const isTaintSource = d.id && _tSrc.has(d.id);
      const isTainted = d.id && _tAll.has(d.id);
      const taintBorder = isTaintSource ? 'border-red' : isTainted ? 'border-yellow border-dashed' : 'border-surface1';
      card.className = `bg-surface0 border ${taintBorder} rounded-lg p-3 hover:border-mauve/50 cursor-pointer transition-colors`;
      card.onclick = () => showDetail(d);

      if (d.id) {
        const name = d.id || '';
        const short = name.includes('.') ? name.split('.').slice(1).join('.') : name;
        const kind = d.kind || '';
        const val = d.value || '';
        const hasEv = d.evidence && d.evidence.length > 0;
        const verified = hasEv && d.evidence[0].verified;
        const taintTag = isTaintSource ? '<span class="text-red">&#x2716; taint source</span>'
          : isTainted ? '<span class="text-yellow">&#x26a0; tainted</span>' : '';

        // Diff cards get patronus dot + state-aware styling (color-mixed)
        if (kind === 'diff' && d.diff) {
          const df = d.diff;
          const contKeys = df.contaminated ? Object.keys(df.contaminated) : [];
          const dotCls = df.coherent ? (contKeys.length ? 'warn' : '') : 'tainted';
          const stIcon = df.coherent ? '&#x2713;' : '&#x2260;';
          const stLabel = df.coherent ? 'coherent' : 'divergent';
          const pri = diffTextPrimary(d.id);
          const sec = diffTextSecondary(d.id);
          const mut = diffTextMuted(d.id);
          const brd = diffBorderColor(d.id);
          card.style.borderColor = brd;
          card.innerHTML = `
            <div class="flex items-start justify-between gap-2 mb-1">
              <div class="flex items-center gap-2">
                <div class="patronus-dot w-3 h-3 ${dotCls}"></div>
                <span class="text-xs font-bold truncate" style="color:${pri}" title="${esc(name)}">${esc(short)}</span>
              </div>
              <span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold ${kindColor(kind)} text-crust">${esc(kind)}</span>
            </div>
            <div class="text-xs truncate mb-1" style="color:${mut}">${esc(df.replace)} → ${esc(df['with'])}</div>
            <div class="flex items-center gap-2 text-[10px]">
              <span style="color:${sec}">${stIcon} ${stLabel}</span>
              ${d.depth > 0 ? `<span class="text-overlay0">depth ${d.depth}</span>` : ''}
              ${taintTag}
            </div>
          `;
        } else {
        card.innerHTML = `
          <div class="flex items-start justify-between gap-2 mb-1">
            <span class="text-xs font-bold text-text truncate" title="${esc(name)}">${esc(short)}</span>
            <span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold ${kindColor(kind)} text-crust">${esc(kind)}</span>
          </div>
          ${val ? `<div class="text-xs text-subtext truncate mb-1" title="${esc(val)}">${esc(val.length > 80 ? val.slice(0,77)+'...' : val)}</div>` : ''}
          <div class="flex items-center gap-2 text-[10px] text-overlay0">
            ${d.inputs && d.inputs.length ? `<span>&#x2190; ${d.inputs.length} inputs</span>` : ''}
            ${hasEv ? `<span class="${verified ? 'text-green' : 'text-yellow'}">${verified ? '&#x2713; verified' : '&#x25cb; unverified'}</span>` : ''}
            ${d.depth > 0 ? `<span>depth ${d.depth}</span>` : ''}
            ${taintTag}
          </div>
        `;
        }
      } else if (FORM_TYPE === 'sr') {
        card.innerHTML = `
          <div class="flex items-center gap-2 mb-1">
            <span class="text-xs font-bold text-sky">${esc(d.doc)}</span>
            <span class="text-[10px] text-overlay0">:${esc(d.line)}</span>
          </div>
          <div class="text-xs text-subtext truncate">${esc(d.ctx)}</div>
          ${d.callers ? `<div class="text-[10px] text-overlay0 mt-1">${esc(d.callers)}</div>` : ''}
        `;
      } else if (FORM_TYPE === 'dx') {
        card.innerHTML = `
          <div class="flex items-start justify-between gap-2 mb-1">
            <span class="text-xs font-bold text-text truncate">${esc(d.id)}</span>
            <span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold bg-red text-crust">${esc(d.category)}</span>
          </div>
          ${d.detail ? `<div class="text-xs text-subtext">${esc(d.detail)}</div>` : ''}
          <div class="text-[10px] text-overlay0">${esc(d.kind)} / ${esc(d.type)}</div>
        `;
      } else if (FORM_TYPE === 'hn') {
        const present = (d.lenses || []).filter(l => l != null);
        const total = (d.lenses || []).length;
        const diverges = present.length > 1 && present.some(l => l.value !== present[0].value || l.kind !== present[0].kind);
        card.innerHTML = `
          <div class="flex items-start justify-between gap-2 mb-1">
            <span class="text-xs font-bold text-teal">${esc(d.id)}</span>
            ${d.kind ? `<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold bg-teal text-crust">${esc(d.kind)}</span>` : ''}
          </div>
          <div class="flex items-center gap-2 text-[10px] text-overlay0">
            <span>${present.length}/${total} lenses</span>
            ${diverges ? '<span class="text-yellow">divergent</span>' : '<span class="text-green">same</span>'}
          </div>
          ${present.length === 1 && present[0].value ? `<div class="text-xs text-subtext truncate">${esc(present[0].value)}</div>` : ''}
        `;
      }
      grid.appendChild(card);
    });

    section.appendChild(header);
    section.appendChild(grid);
    container.appendChild(section);
  });
}
