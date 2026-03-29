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
