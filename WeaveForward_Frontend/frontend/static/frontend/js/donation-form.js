/* ── Drag-and-drop image upload ── */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.drop').forEach(zone => {
    const input = zone.querySelector('input[type="file"]') || zone.parentElement?.querySelector('input[type="file"]');
    if (!input) return;

    ['dragenter', 'dragover'].forEach(eventName => {
      zone.addEventListener(eventName, event => {
        event.preventDefault();
        zone.classList.add('drag-over');
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      zone.addEventListener(eventName, event => {
        event.preventDefault();
        zone.classList.remove('drag-over');
      });
    });

    zone.addEventListener('drop', event => {
      const files = event.dataTransfer?.files;
      if (!files?.length) return;
      input.files = files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
});

/* ── Material Dropdown (click-to-open + search inside) ── */
function toggleMatDropdown(trigger) {
  if (trigger.classList.contains('disabled')) return;
  const wrap = trigger.closest('.ss-wrap');
  const list = wrap.querySelector('.ss-list');
  const isOpen = !list.classList.contains('hidden');
  document.querySelectorAll('.ss-list').forEach(l => l.classList.add('hidden'));
  document.querySelectorAll('.ss-wrap').forEach(w => w.classList.remove('open'));
  if (!isOpen) {
    list.classList.remove('hidden');
    wrap.classList.add('open');
    const search = list.querySelector('.mat-search');
    if (search) { search.value = ''; search.focus(); }
    list.querySelectorAll('.mat-item').forEach(it => it.style.display = '');
  }
}

function filterMatList(inp) {
  const q = inp.value.trim().toLowerCase();
  inp.closest('.ss-list').querySelectorAll('.mat-item').forEach(it => {
    it.style.display = q && !it.textContent.toLowerCase().includes(q) ? 'none' : '';
  });
}

document.addEventListener('click', e => {
  if (!e.target.closest('.ss-wrap')) {
    document.querySelectorAll('.ss-list').forEach(l => l.classList.add('hidden'));
    document.querySelectorAll('.ss-wrap').forEach(w => w.classList.remove('open'));
  }
});
