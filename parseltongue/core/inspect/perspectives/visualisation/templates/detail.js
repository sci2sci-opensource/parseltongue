// ── Derivation tree builder ──
function buildDerivationTree(rootId, maxDepth) {
  maxDepth = maxDepth || 20;
  const visited = new Set();
  function walk(id, depth) {
    const node = ITEM_BY_ID[id];
    const entry = {
      id: id,
      kind: node ? node.kind : '?',
      value: node ? node.value : '',
      depth: node ? node.depth : -1,
      children: [],
      cycle: false,
      external: !node,
      outsideFocus: node ? !!node.external : !node
    };
    if (visited.has(id) || depth >= maxDepth) {
      entry.cycle = visited.has(id);
      return entry;
    }
    visited.add(id);
    if (node && node.inputs) {
      node.inputs.forEach(inp => {
        const inpName = typeof inp === 'string' ? inp : inp.name;
        entry.children.push(walk(inpName, depth + 1));
      });
    }
    return entry;
  }
  return walk(rootId, 0);
}

function renderTree(tree) {
  // Render as nested HTML tree with connectors
  function renderNode(node, isLast, prefix) {
    const connector = prefix === '' ? '' : (isLast ? '&#x2514;&#x2500;&#x2500; ' : '&#x251c;&#x2500;&#x2500; ');
    const kindCls = kindText(node.kind);
    const badge = `<span class="px-1 py-0.5 rounded text-[9px] ${kindColor(node.kind)} text-crust">${esc(node.kind)}</span>`;
    const short = node.id.includes('.') ? node.id.split('.').slice(1).join('.') : node.id;
    const nameSpan = node.external
      ? `<span class="text-overlay0 italic">${esc(short)}</span>`
      : node.outsideFocus
        ? `<span class="text-subtext cursor-pointer hover:text-mauve" onclick="showDetail(ITEM_BY_ID['${node.id.replace(/'/g, "\\'")}'])">${esc(short)}</span>`
        : `<span class="text-text font-bold cursor-pointer hover:text-mauve" onclick="showDetail(ITEM_BY_ID['${node.id.replace(/'/g, "\\'")}'])">${esc(short)}</span>`;
    const valSnip = node.value ? `<span class="text-subtext ml-1 text-[9px]">= ${esc(String(node.value).slice(0, 40))}</span>` : '';
    const layerTag = node.depth >= 0 ? `<span class="text-[9px] text-overlay0 ml-1">L${node.depth}</span>` : '';
    const cycleTag = node.cycle ? ' <span class="text-yellow text-[9px]">&#x21bb; cycle</span>' : '';

    let html = `<div class="flex items-center gap-1 py-0.5">`;
    html += `<span class="text-surface2 whitespace-pre font-mono text-[10px]">${prefix}${connector}</span>`;
    html += `${nameSpan} ${badge}${valSnip}${layerTag}${cycleTag}`;
    html += `</div>`;

    if (node.children.length > 0 && !node.cycle) {
      const childPrefix = prefix === '' ? '' : (prefix + (isLast ? '&nbsp;&nbsp;&nbsp;&nbsp;' : '&#x2502;&nbsp;&nbsp;&nbsp;'));
      node.children.forEach((child, i) => {
        html += renderNode(child, i === node.children.length - 1, childPrefix || '');
      });
    }
    return html;
  }
  return renderNode(tree, true, '');
}

// ── Focus helpers (switch view + highlight node) ──
// Graph and layers views register these callbacks on init.
window._graphFocusNode = null;
window._layersFocusNode = null;

function focusInGraph(name) {
  searchEl.value = name;
  searchQuery = name.toLowerCase();
  switchView('graph');
  setTimeout(() => {
    if (window._graphFocusNode) window._graphFocusNode(name);
  }, 100);
}
function focusInLayers(name) {
  searchEl.value = name;
  searchQuery = name.toLowerCase();
  switchView('layers');
  setTimeout(() => {
    if (window._layersFocusNode) window._layersFocusNode(name);
  }, 100);
}

// ── Detail panel ──
const panel = document.getElementById('detail-panel');
const appEl = document.getElementById('app');
document.getElementById('detail-close').onclick = () => {
  panel.classList.add('translate-x-full');
  appEl.classList.remove('detail-open');
  setTimeout(_syncViewHeight, 220);
};

function _itemType(d) {
  // Detect item type from properties, not FORM_TYPE
  if (d.doc && d.callers !== undefined) return 'sr';
  if (d.category && d.type !== undefined) return 'dx';
  if (d.lenses !== undefined) return 'hn';
  if (d.id) return 'ln';
  return FORM_TYPE;
}

function showDetail(d) {
  if (!d) return;
  panel.classList.remove('translate-x-full');
  appEl.classList.add('detail-open');
  setTimeout(_syncViewHeight, 220);
  document.getElementById('detail-title').textContent = d.id || d.doc || '';
  const body = document.getElementById('detail-body');
  let html = '';
  const itemType = _itemType(d);

  if (itemType === 'ln') {
    html += `<div class="space-y-3">`;
    if (d.external) {
      html += `<div class="bg-surface0 border border-surface2 rounded px-2 py-1 text-[10px] text-overlay0 mb-2">Outside current focus &mdash; data from probe graph</div>`;
    }
    html += `<div><span class="text-overlay0">name:</span> <span class="text-text font-bold">${esc(d.id)}</span></div>`;
    html += `<div><span class="text-overlay0">kind:</span> <span class="${kindText(d.kind)} font-bold">${esc(d.kind)}</span></div>`;
    // ── Diff-specific rendering (color-mixed patronus palette) ──
    if (d.kind === 'diff' && d.diff) {
      const df = d.diff;
      const contKeys = df.contaminated ? Object.keys(df.contaminated) : [];
      const hasContOnly = df.coherent && contKeys.length > 0;
      const pri = diffTextPrimary(d.id);
      const sec = diffTextSecondary(d.id);
      const mut = diffTextMuted(d.id);
      const brd = diffBorderColor(d.id);
      let icon, stLabel;
      if (df.coherent && !hasContOnly) {
        icon = '&#x2713;'; stLabel = 'Coherent';
      } else if (hasContOnly) {
        icon = '&#x26a0;'; stLabel = 'Coherent (contaminated)';
      } else {
        icon = '&#x2260;'; stLabel = 'Divergent';
      }
      html += `<div class="mt-1 flex items-center gap-2"><span class="font-bold" style="color:${pri}">${icon} ${stLabel}</span></div>`;
      html += `<div class="mt-2 rounded-lg p-3 space-y-2" style="background:var(--crust);border:1px solid ${brd}">`;
      // Branch A (replace)
      html += `<div class="flex items-center gap-2">`;
      html += `<span class="text-[10px] w-14 shrink-0" style="color:${mut}">replace</span>`;
      html += `<span class="font-bold cursor-pointer hover:text-mauve" style="color:${pri}" onclick="showDetail(ITEM_BY_ID['${(df.replace||'').replace(/'/g, "\\'")}'])">${esc(df.replace)}</span>`;
      if (df.value_a != null) html += `<span class="text-xs" style="color:${sec}">= ${esc(df.value_a)}</span>`;
      html += `</div>`;
      // Branch B (with)
      html += `<div class="flex items-center gap-2">`;
      html += `<span class="text-[10px] w-14 shrink-0" style="color:${mut}">with</span>`;
      html += `<span class="font-bold cursor-pointer hover:text-mauve" style="color:${pri}" onclick="showDetail(ITEM_BY_ID['${(df['with']||'').replace(/'/g, "\\'")}'])">${esc(df['with'])}</span>`;
      if (df.value_b != null) html += `<span class="text-xs" style="color:${sec}">= ${esc(df.value_b)}</span>`;
      html += `</div>`;
      // Divergences — downstream terms that change under substitution
      if (df.divergences) {
        const divKeys = Object.keys(df.divergences);
        if (divKeys.length) {
          html += `<div class="border-t pt-2 mt-2" style="border-color:${brd}">`;
          html += `<div class="text-[10px] font-bold mb-1" style="color:${pri}">Downstream divergences (${divKeys.length})</div>`;
          divKeys.forEach(k => {
            const dv = df.divergences[k];
            const nameSpan = ITEM_BY_ID[k]
              ? `<span class="text-text font-bold cursor-pointer hover:text-mauve" onclick="showDetail(ITEM_BY_ID['${k.replace(/'/g, "\\'")}'])">${esc(k)}</span>`
              : `<span class="text-text">${esc(k)}</span>`;
            if (dv && dv.before !== undefined) {
              html += `<div class="text-xs mt-1">${nameSpan}</div>`;
              html += `<div class="text-[10px] ml-3 text-subtext">${esc(dv.before)} <span style="color:${pri}">&rarr;</span> ${esc(dv.after)}</div>`;
            } else {
              html += `<div class="text-xs mt-1">${nameSpan}: <span style="color:${pri}">${esc(String(dv))}</span></div>`;
            }
          });
          html += `</div>`;
        } else if (df.coherent) {
          html += `<div class="border-t pt-2 mt-2" style="border-color:${brd}">`;
          html += `<div class="text-[10px]" style="color:${sec}">&#x2713; No downstream divergences</div>`;
          html += `</div>`;
        }
      }
      // Contaminated — other diffs reference the same replace side (warning, not failure)
      if (df.contaminated) {
        const contKeys = Object.keys(df.contaminated);
        if (contKeys.length) {
          html += `<div class="border-t pt-2 mt-2" style="border-color:${brd}">`;
          html += `<div class="text-[10px] font-bold mb-1" style="color:${pri}">Contaminated diffs (${contKeys.length})</div>`;
          html += `<div class="text-[10px] mb-1" style="color:${mut}">Other diffs reference the same replace side — not a real value divergence.</div>`;
          contKeys.forEach(k => {
            const cv = df.contaminated[k];
            const nameSpan = ITEM_BY_ID[k]
              ? `<span class="text-text font-bold cursor-pointer hover:text-mauve" onclick="showDetail(ITEM_BY_ID['${k.replace(/'/g, "\\'")}'])">${esc(k)}</span>`
              : `<span class="text-text">${esc(k)}</span>`;
            html += `<div class="text-xs mt-1">${nameSpan}</div>`;
            html += `<div class="text-[10px] ml-3" style="color:${mut}">${esc(cv.before)}</div>`;
          });
          html += `</div>`;
        }
      }
      html += `</div>`;
    } else {
      const noVal = !d.value || d.value === '()' || d.value === "''" || d.value === '""' || d.value === "''";
      const displayVal = noVal ? 'No value' : d.value;
      html += `<div><span class="text-overlay0">value:</span><div class="mt-1 bg-surface0 rounded p-2 text-xs whitespace-pre-wrap ${noVal ? 'text-overlay0 italic' : ''}">${esc(displayVal)}</div></div>`;
    }
    if (d.depth > 0) html += `<div><span class="text-overlay0">depth:</span> ${d.depth}</div>`;

    // ── Focus actions ──
    html += `<div class="flex gap-2 pt-1">`;
    html += `<button class="px-2 py-1 rounded text-[10px] bg-surface0 text-subtext hover:bg-surface1 hover:text-mauve border border-surface2" onclick="focusInLayers('${d.id.replace(/'/g, "\\'")}')">Focus in Layers</button>`;
    html += `<button class="px-2 py-1 rounded text-[10px] bg-surface0 text-subtext hover:bg-surface1 hover:text-mauve border border-surface2" onclick="focusInGraph('${d.id.replace(/'/g, "\\'")}')">Focus in Graph</button>`;
    html += `</div>`;

    // ── Definition (WFF) ──
    if (d.definition) {
      html += `<div class="border-t border-surface2 pt-3"><span class="text-overlay0 font-bold">Definition</span>`;
      html += `<div class="mt-1 bg-crust rounded-lg p-3 text-xs whitespace-pre-wrap font-mono text-lavender">${esc(d.definition)}</div>`;
      html += `</div>`;
    }

    // ── Evidence with quotes ──
    if (d.evidence && d.evidence.length) {
      html += `<div class="border-t border-surface2 pt-3"><span class="text-overlay0 font-bold">Evidence</span>`;
      d.evidence.forEach(ev => {
        const st = ev.status || (ev.verified ? 'verified' : 'unverified');
        if (st === 'derived') {
          html += `<div class="mt-2 text-xs text-blue">&#x2713; derived (proven by derivation)</div>`;
          return;
        }
        html += `<div class="mt-2 bg-crust rounded-lg p-3 space-y-1">`;
        if (ev.doc) html += `<div class="text-xs"><span class="text-overlay0">doc:</span> <span class="text-sky">${esc(ev.doc)}</span></div>`;
        if (ev.quotes && ev.quotes.length) {
          const ctxs = ev.quote_contexts || {};
          const details = ev.quote_details || {};
          ev.quotes.forEach(q => {
            const bc = st === 'verified' ? 'border-green' : 'border-yellow';
            const det = details[q];
            const matches = det && det.all_matches && det.all_matches.length > 1 ? det.all_matches : null;
            html += `<div class="text-xs bg-surface0 rounded p-2 mt-1 whitespace-pre-wrap border-l-2 ${bc}">`;
            if (matches) {
              // Multiple matches — same block, separated by ...
              matches.forEach((m, i) => {
                if (i > 0) html += `<div class="text-overlay0 text-center my-1">&#x2026;</div>`;
                const mctx = m.context;
                const isCurrent = m.original_line === (det.line || -1);
                const tag = isCurrent ? '&#x25c6;' : '&#x25cb;';
                const tagCls = isCurrent ? 'text-sky' : 'text-overlay0';
                html += `<div class="flex gap-2"><span class="text-[9px] text-sky">L${m.original_line}</span><span class="text-[9px] text-overlay0">${esc(m.strategy)}</span><span class="text-[9px] ${tagCls}">${tag}</span></div>`;
                if (mctx && (mctx.before || mctx.after)) {
                  if (mctx.before) html += `<span class="text-overlay0">${esc(mctx.before)}</span>`;
                  html += `<span class="font-bold text-text bg-highlight rounded-sm px-0.5">${esc(q)}</span>`;
                  if (mctx.after) html += `<span class="text-overlay0">${esc(mctx.after)}</span>`;
                } else {
                  html += `<span class="font-bold text-text">${esc(q)}</span>`;
                }
              });
            } else {
              // Single match
              const ctx = ctxs[q];
              const lineBadge = det && det.line ? `<span class="text-[9px] text-sky">L${det.line}</span>` : '';
              const confBadge = det && det.confidence != null ? `<span class="text-[9px] text-overlay0">${Math.round(det.confidence * 100)}%</span>` : '';
              if (lineBadge || confBadge) html += `<div class="flex gap-2">${lineBadge}${confBadge}</div>`;
              if (ctx && (ctx.before || ctx.after)) {
                if (ctx.before) html += `<span class="text-overlay0">${esc(ctx.before)}</span>`;
                html += `<span class="font-bold text-text bg-highlight rounded-sm px-0.5">${esc(q)}</span>`;
                if (ctx.after) html += `<span class="text-overlay0">${esc(ctx.after)}</span>`;
              } else {
                html += `<span class="font-bold text-text">${esc(q)}</span>`;
              }
            }
            html += `</div>`;
          });
        } else if (ev.quote) {
          const bc = st === 'verified' ? 'border-green' : 'border-yellow';
          html += `<div class="text-xs bg-surface0 rounded p-2 mt-1 whitespace-pre-wrap border-l-2 ${bc}">${esc(ev.quote)}</div>`;
        }
        if (ev.explanation) html += `<div class="text-xs text-subtext mt-1">${esc(ev.explanation)}</div>`;
        if (ev.label) html += `<div class="text-xs text-subtext mt-1">${esc(ev.label)}</div>`;
        const stColor = st === 'verified' ? 'text-green' : st === 'manual' ? 'text-peach' : 'text-yellow';
        const stIcon = st === 'verified' ? '&#x2713;' : st === 'manual' ? '&#x270e;' : '&#x25cb;';
        html += `<div class="text-[10px] ${stColor}">${stIcon} ${st}</div>`;
        html += `</div>`;
      });
      html += `</div>`;
    }

    // ── Taint status ──
    {
      const _td = (typeof TAINT_DATA !== 'undefined') ? TAINT_DATA : {sources:[], tainted:[], reasons:{}};
      const _tSrc = new Set(_td.sources);
      const _tAll = new Set(_td.tainted);
      if (_tAll.has(d.id)) {
        const isSource = _tSrc.has(d.id);
        const reason = (_td.reasons || {})[d.id] || (isSource ? 'taint source' : 'tainted');
        html += `<div class="border-t border-surface2 pt-3"><span class="text-overlay0 font-bold">Taint</span>`;
        html += `<div class="mt-1 bg-crust rounded-lg p-3 text-xs">`;
        html += `<div class="${isSource ? 'text-red' : 'text-yellow'} font-bold">${isSource ? '&#x2716; Taint source' : '&#x26a0; Tainted'}</div>`;
        html += `<div class="text-subtext mt-1">${esc(reason)}</div>`;
        html += `</div></div>`;
      }
    }

    // ── Derivation tree (last) ──
    if (d.inputs && d.inputs.length) {
      const tree = buildDerivationTree(d.id, 15);
      html += `<div class="border-t border-surface2 pt-3">`;
      html += `<div class="text-overlay0 font-bold mb-2">Derivation path</div>`;
      html += `<div class="bg-crust rounded-lg p-3 text-xs overflow-x-auto">${renderTree(tree)}</div>`;
      html += `</div>`;
    }
    html += `</div>`;
  } else if (itemType === 'sr') {
    html += `<div class="space-y-2">`;
    html += `<div><span class="text-overlay0">document:</span> <span class="text-sky font-bold">${esc(d.doc)}</span></div>`;
    html += `<div><span class="text-overlay0">line:</span> ${esc(String(d.line))}</div>`;
    if (d.ctx) html += `<div class="bg-surface0 rounded p-2 text-xs whitespace-pre-wrap">${esc(d.ctx)}</div>`;
    if (d.callers && d.callers.length) {
      html += `<div class="border-t border-surface2 pt-2"><span class="text-overlay0 font-bold">Callers (${d.callers.length})</span>`;
      d.callers.forEach(c => {
        const name = typeof c === 'object' ? c.name : c;
        const overlap = typeof c === 'object' ? c.overlap : null;
        const short = name.includes('.') ? name.split('.').slice(1).join('.') : name;
        const structItem = ITEM_BY_ID[name];
        const kindBadge = structItem ? `<span class="px-1 py-0.5 rounded text-[9px] ${kindColor(structItem.kind)} text-crust">${esc(structItem.kind)}</span>` : '';
        html += `<div class="flex items-center gap-2 mt-1 cursor-pointer hover:bg-surface0 rounded px-1 py-0.5" onclick="showDetail(ITEM_BY_ID['${name.replace(/'/g, "\\'")}'] || {doc:'${esc(d.doc)}',line:'${esc(String(d.line))}',ctx:'${esc(name)}',callers:[]})">`;
        html += `<span class="text-xs text-lavender font-bold">${esc(short)}</span> ${kindBadge}`;
        if (overlap != null) html += `<span class="text-[10px] text-overlay0">${Math.round(overlap * 100)}% overlap</span>`;
        html += `</div>`;
      });
      html += `</div>`;
    }
    html += `</div>`;
  } else if (itemType === 'dx') {
    html += `<div class="space-y-2">`;
    html += `<div><span class="text-overlay0">name:</span> <span class="font-bold">${esc(d.id)}</span></div>`;
    html += `<div><span class="text-overlay0">category:</span> <span class="text-red">${esc(d.category)}</span></div>`;
    html += `<div><span class="text-overlay0">kind:</span> ${esc(d.kind)}</div>`;
    html += `<div><span class="text-overlay0">type:</span> ${esc(d.type)}</div>`;
    if (d.detail) html += `<div class="bg-surface0 rounded p-2 text-xs whitespace-pre-wrap">${esc(d.detail)}</div>`;
    html += `</div>`;
  } else if (itemType === 'hn') {
    html += `<div class="space-y-3">`;
    html += `<div><span class="text-overlay0">name:</span> <span class="text-teal font-bold">${esc(d.id)}</span></div>`;
    if (d.kind) html += `<div><span class="text-overlay0">kind:</span> <span class="${kindText(d.kind)} font-bold">${esc(d.kind)}</span></div>`;
    if (d.lenses && d.lenses.length) {
      d.lenses.forEach((lens, i) => {
        html += `<div class="border-t border-surface2 pt-2">`;
        html += `<div class="text-[10px] text-overlay0 font-bold mb-1">Lens ${i}</div>`;
        if (lens == null) {
          html += `<div class="text-xs text-overlay0 italic">(absent)</div>`;
        } else {
          if (lens.kind) html += `<div class="text-xs"><span class="text-overlay0">kind:</span> <span class="${kindText(lens.kind)}">${esc(lens.kind)}</span></div>`;
          if (lens.value) html += `<div class="text-xs"><span class="text-overlay0">value:</span> ${esc(lens.value)}</div>`;
          if (lens.depth > 0) html += `<div class="text-xs"><span class="text-overlay0">depth:</span> ${lens.depth}</div>`;
          if (lens.inputs && lens.inputs.length) {
            html += `<div class="text-xs"><span class="text-overlay0">inputs:</span> ${lens.inputs.map(inp => esc(inp)).join(', ')}</div>`;
          }
        }
        html += `</div>`;
      });
    }
    html += `</div>`;
  }
  body.innerHTML = html;
}
