// ── Theme palette (shared, refreshed on toggle) ──
function getColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue('--' + name).trim();
}

const C = {};
function refreshPalette() {
  const names = ['base','mantle','crust','surface0','surface1','surface2',
    'overlay0','text','subtext','green','red','yellow','blue','mauve',
    'teal','peach','flamingo','sky','lavender'];
  names.forEach(n => { C[n] = getColor(n); });
  C.pill = getColor('base-light') || C.surface0;
}
refreshPalette();

// ── Constants ──
const KIND_COLORS = {
  fact:'bg-green',axiom:'bg-peach',defterm:'bg-blue',theorem:'bg-mauve',
  diff:'bg-red',derive:'bg-mauve',evidence:'bg-overlay0','search-result':'bg-green',
  diagnostic:'bg-red',hologram:'bg-teal',document:'bg-sky',input:'bg-surface2',
  lens:'bg-lavender',unknown:'bg-surface2'
};
const KIND_TEXT = {
  fact:'text-green',axiom:'text-peach',defterm:'text-blue',theorem:'text-mauve',
  diff:'text-red',derive:'text-mauve',evidence:'text-overlay0','search-result':'text-green',
  diagnostic:'text-red',hologram:'text-teal',document:'text-sky',lens:'text-lavender'
};
const KIND_DOT_VAR = {
  fact:'green',axiom:'peach',defterm:'blue',theorem:'mauve',
  diff:'red',derive:'mauve',evidence:'overlay0','search-result':'green',
  diagnostic:'red',hologram:'teal',document:'sky',input:'surface2',
  lens:'lavender'
};

function kindColor(k) { return KIND_COLORS[k] || KIND_COLORS.unknown; }
function kindText(k) { return KIND_TEXT[k] || 'text-subtext'; }
function kindDot(k) { return getColor(KIND_DOT_VAR[k] || 'surface2'); }
function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// ── State ──
let activeKinds = new Set();
let searchQuery = '';
let currentView = 'source';

// ── Kind discovery ──
const allKinds = [...new Set(
  DATA.map(d => d.kind || d.category || '')
    .concat(STRUCTURE_DATA.map(d => d.kind || d.category || ''))
)].filter(Boolean).sort();

// ── Filters ──
const filtersEl = document.getElementById('kind-filters');
allKinds.forEach(k => {
  const btn = document.createElement('button');
  btn.className = `px-2 py-0.5 rounded text-xs border border-surface2 ${kindText(k)} hover:bg-surface1 transition-colors`;
  btn.textContent = k;
  btn.dataset.kind = k;
  btn.onclick = () => {
    if (activeKinds.has(k)) { activeKinds.delete(k); btn.classList.remove('bg-surface1','font-bold'); btn.classList.add('bg-transparent'); }
    else { activeKinds.add(k); btn.classList.add('bg-surface1','font-bold'); btn.classList.remove('bg-transparent'); }
    render();
  };
  filtersEl.appendChild(btn);
});

// ── Search with suggestions ──
const searchEl = document.getElementById('search');
const suggestionsEl = document.getElementById('search-suggestions');

// All known node names for suggestions (lazy — ITEM_BY_ID defined later)
let _allNames = null;
function _getAllNames() {
  if (!_allNames) _allNames = Object.keys(ITEM_BY_ID);
  return _allNames;
}

function _updateSuggestions(query) {
  if (!query || query.length < 2) {
    suggestionsEl.classList.add('hidden');
    return;
  }
  const q = query.toLowerCase();
  // Exact prefix matches first, then substring matches
  const prefix = [];
  const substr = [];
  _getAllNames().forEach(name => {
    const short = name.includes('.') ? name.split('.').slice(1).join('.') : name;
    const low = name.toLowerCase();
    const slowLow = short.toLowerCase();
    if (slowLow.startsWith(q) || low.startsWith(q)) prefix.push(name);
    else if (low.includes(q) || slowLow.includes(q)) substr.push(name);
  });
  const matches = prefix.concat(substr).slice(0, 12);
  if (!matches.length) {
    suggestionsEl.classList.add('hidden');
    return;
  }
  suggestionsEl.innerHTML = matches.map(name => {
    const item = ITEM_BY_ID[name];
    const kind = item ? item.kind : '';
    const dotVar = KIND_DOT_VAR[kind] || 'surface2';
    const short = name.includes('.') ? name.split('.').slice(1).join('.') : name;
    const val = item && item.value ? (' = ' + esc(String(item.value).slice(0, 30))) : '';
    return `<div class="search-suggestion px-3 py-1.5 cursor-pointer hover:bg-surface0 flex items-center gap-2 text-sm" data-name="${esc(name)}">
      <span class="w-2 h-2 rounded-full shrink-0" style="background:var(--${dotVar})"></span>
      <span class="text-text truncate">${esc(short)}</span>
      <span class="text-overlay0 text-xs truncate">${esc(kind)}</span>
      <span class="text-subtext text-xs ml-auto shrink-0">${val}</span>
    </div>`;
  }).join('');
  suggestionsEl.classList.remove('hidden');
}

suggestionsEl.addEventListener('click', (e) => {
  const row = e.target.closest('.search-suggestion');
  if (!row) return;
  const name = row.dataset.name;
  searchEl.value = name;
  searchQuery = name.toLowerCase();
  suggestionsEl.classList.add('hidden');
  focusCurrentView(name);
});

// Close suggestions on outside click or Escape
document.addEventListener('click', (e) => {
  if (!e.target.closest('#search') && !e.target.closest('#search-suggestions')) {
    suggestionsEl.classList.add('hidden');
  }
});
searchEl.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') suggestionsEl.classList.add('hidden');
  if (e.key === 'Enter') {
    const first = suggestionsEl.querySelector('.search-suggestion');
    if (first && !suggestionsEl.classList.contains('hidden')) {
      e.preventDefault();
      const name = first.dataset.name;
      searchEl.value = name;
      searchQuery = name.toLowerCase();
      suggestionsEl.classList.add('hidden');
      focusCurrentView(name);
    }
  }
});

searchEl.addEventListener('input', (e) => {
  searchQuery = e.target.value.toLowerCase();
  _updateSuggestions(e.target.value);
  render();
});

// ── Focus dispatch for current view ──
function focusCurrentView(name) {
  const item = ITEM_BY_ID[name];
  if (currentView === 'graph' && window._graphFocusNode) {
    window._graphFocusNode(name);
  } else if (currentView === 'layers' && window._layersFocusNode) {
    window._layersFocusNode(name);
  } else if (item) {
    showDetail(item);
  }
  render();
}

// ── View toggle ──
const VIEW_BTNS = ['source', 'structure', 'layers', 'graph'];
VIEW_BTNS.forEach(v => {
  document.getElementById('btn-' + v).onclick = () => switchView(v);
});

function switchView(v) {
  currentView = v;
  VIEW_BTNS.forEach(id => {
    document.getElementById(id + '-view').classList.toggle('hidden', v !== id);
    document.getElementById('btn-' + id).className = v === id
      ? 'px-3 py-1 rounded-lg text-xs bg-mauve text-crust font-bold'
      : 'px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext hover:bg-surface1';
  });
  // Adjust full-height views to account for actual header size
  _syncViewHeight();
  if (v === 'source') renderSource();
  if (v === 'structure') render();
  if (v === 'graph') renderGraph();
  if (v === 'layers') renderLayers();
}

function _syncViewHeight() {
  const header = document.querySelector('#app > .sticky');
  if (!header) return;
  const h = header.offsetHeight;
  ['layers-view', 'graph-view'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.height = 'calc(100vh - ' + h + 'px)';
  });
}
window.addEventListener('resize', _syncViewHeight);

// ── Filter logic ──
function filtered(source) {
  const items = source || (currentView === 'structure' ? STRUCTURE_DATA : DATA);
  return items.filter(d => {
    const k = d.kind || d.category || '';
    if (activeKinds.size > 0 && !activeKinds.has(k)) return false;
    if (searchQuery) {
      const hay = JSON.stringify(d).toLowerCase();
      return hay.includes(searchQuery);
    }
    return true;
  });
}

// ── Data index for tree walks ──
const ITEM_BY_ID = {};
DATA.forEach(d => { if (d.id) ITEM_BY_ID[d.id] = d; });
STRUCTURE_DATA.forEach(d => { if (d.id) ITEM_BY_ID[d.id] = d; });

function highlightInput(name) {
  searchEl.value = name;
  searchQuery = name.toLowerCase();
  render();
}
