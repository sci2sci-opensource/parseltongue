/* Shared JS for parseltongue pages — theme toggle + tabs */

// ── Theme ──
function initTheme() {
  var saved = localStorage.getItem('pt-theme');
  if (!saved) saved = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  updateToggleIcon(saved);
}
function toggleTheme() {
  var current = document.documentElement.getAttribute('data-theme') || 'dark';
  var next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('pt-theme', next);
  updateToggleIcon(next);
}
function updateToggleIcon(theme) {
  var btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'dark' ? '\u2600' : '\u263E';
}
initTheme();

// ── Copy buttons on <pre> and .prompt blocks ──
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('pre, .prompt').forEach(function(block) {
    var btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.textContent = 'copy';
    btn.addEventListener('click', function() {
      var code = block.querySelector('code') || block.querySelector('p');
      var text = code ? code.textContent : block.textContent;
      navigator.clipboard.writeText(text).then(function() {
        btn.textContent = 'copied';
        btn.classList.add('copied');
        setTimeout(function() {
          btn.textContent = 'copy';
          btn.classList.remove('copied');
        }, 1500);
      });
    });
    block.appendChild(btn);
  });
});

// ── Tabs ──
function switchTab(group, id) {
  document.querySelectorAll('[data-tab-group="' + group + '"]').forEach(function(el) {
    el.classList.toggle('active', el.getAttribute('data-tab') === id);
  });
  document.querySelectorAll('[data-panel-group="' + group + '"]').forEach(function(el) {
    el.classList.toggle('active', el.getAttribute('data-panel') === id);
  });
}

// ── sci2sci badge (skip on pgmd-rendered pages — they have their own viz badge) ──
(function() {
  if (document.querySelector('.pgmd-notebook, #DATA')) return;
  var badge = document.createElement('div');
  badge.style.cssText = 'position:fixed;bottom:1rem;right:1rem;z-index:50;'
    + 'background:color-mix(in srgb,var(--mantle) 95%,transparent);backdrop-filter:blur(8px);'
    + 'border:1px solid var(--surface1);border-radius:0.5rem;padding:0.625rem 0.75rem;'
    + 'font-size:11px;line-height:1.6;max-width:290px;box-shadow:0 4px 12px rgba(0,0,0,0.3);';
  badge.innerHTML =
    '<div style="color:var(--subtext)">Developed by <a href="https://www.sci2sci.com" target="_blank" rel="noopener" style="color:var(--lavender);font-weight:600">sci2sci</a></div>'
    + '<div style="color:var(--overlay0);margin-top:2px">Need to convert data and documents to knowledge <a href="https://www.sci2sci.com/safe-principles" target="_blank" rel="noopener" style="color:var(--green);font-weight:500">safely</a> at enterprise scale?</div>'
    + '<div style="margin-top:2px">Try <a href="https://www.sci2sci.com" target="_blank" rel="noopener" style="color:var(--mauve);font-weight:700">VectorCat</a>!</div>';
  document.body.appendChild(badge);
})();
