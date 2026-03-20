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

// ── Search ──
const searchEl = document.getElementById('search');
searchEl.addEventListener('input', (e) => { searchQuery = e.target.value.toLowerCase(); render(); });

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
  if (v === 'source') renderSource();
  if (v === 'structure') render();
  if (v === 'graph') renderGraph();
  if (v === 'layers') renderLayers();
}

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
