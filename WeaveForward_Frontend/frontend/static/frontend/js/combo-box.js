function openDropdown(inp) { document.querySelectorAll('.ss-list').forEach(l => l.classList.add('hidden')); document.querySelectorAll('.ss-wrap').forEach(w => w.classList.remove('open')); const lst = inp.closest('.ss-wrap').querySelector('.ss-list'); if(lst) { lst.classList.remove('hidden'); filterDropdown(inp); } }
function filterDropdown(inp) { const q = inp.value.toLowerCase(); const lst = inp.closest('.ss-wrap').querySelector('.ss-list'); const items = lst.querySelectorAll('.mat-item'); let anyVisible = false; items.forEach(el => { const match = el.textContent.toLowerCase().includes(q); el.style.display = match ? '' : 'none'; if (match) anyVisible = true; }); lst.classList.toggle('hidden', !anyVisible); }
function closeDropdown(inp) { setTimeout(() => { const lst = inp.closest('.ss-wrap').querySelector('.ss-list'); if(lst) lst.classList.add('hidden'); }, 150); }
function pickItem(el) { const wrap = el.closest('.ss-wrap'); const inp = wrap.querySelector('input'); inp.value = el.textContent; wrap.querySelector('.ss-list').classList.add('hidden'); debounceLoad(inp); const card = wrap.closest('.restored-card'); if(card) { card.setAttribute('data-changed', 'true'); } }
function debounceLoad(el) { if (window._loadMatTimer) clearTimeout(window._loadMatTimer); window._loadMatTimer = setTimeout(() => loadMaterials(el), 300); }

document.addEventListener('DOMContentLoaded', () => {
  const cards = document.getElementById('cards');
  if (!cards) return;
  cards.addEventListener('focusin', e => {
    if (e.target.matches('.type-sel, .brand-sel')) openDropdown(e.target);
  });
  cards.addEventListener('keydown', e => {
    if (e.target.matches('.type-sel') && e.key.length === 1 && !/^[A-Za-z\s-]$/.test(e.key)) e.preventDefault();
  });
  cards.addEventListener('input', e => {
    if (e.target.matches('.type-sel, .brand-sel')) { filterDropdown(e.target); debounceLoad(e.target); }
  });
  cards.addEventListener('focusout', e => {
    if (e.target.matches('.type-sel, .brand-sel')) closeDropdown(e.target);
  });
  cards.addEventListener('mousedown', e => {
    const item = e.target.closest('.ss-wrap:not(.mat-search-wrap) .mat-item');
    if (item) { e.preventDefault(); pickItem(item); }
  });
});
