(function () {
  /* ── Custom Select Dropdowns ── */
  function initCustomSelect(select) {
    if (select.dataset.customSelectInitialized) return;
    select.dataset.customSelectInitialized = 'true';

    const wrapper = document.createElement('div');
    wrapper.className = 'custom-select-wrapper';
    if (select.disabled) wrapper.classList.add('disabled');
    
    wrapper.style.position = 'relative';
    wrapper.style.width = '100%';

    // Hide original select visually but keep it focusable and validatable
    select.style.position = 'absolute';
    select.style.opacity = '0';
    select.style.pointerEvents = 'none';
    select.style.width = '1px';
    select.style.height = '1px';
    select.style.padding = '0';
    select.style.margin = '-1px';
    select.style.overflow = 'hidden';
    select.style.clip = 'rect(0, 0, 0, 0)';
    select.style.border = '0';
    select.setAttribute('tabindex', '-1');

    const trigger = document.createElement('div');
    trigger.className = 'custom-select-trigger';
    
    const arrow = document.createElement('span');
    arrow.className = 'custom-select-arrow';
    arrow.innerHTML = `
      <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
        <polyline points="6,9 12,15 18,9"/>
      </svg>
    `;
    trigger.appendChild(document.createTextNode(''));
    trigger.appendChild(arrow);

    const menu = document.createElement('div');
    menu.className = 'custom-select-menu hidden';

    wrapper.appendChild(trigger);
    wrapper.appendChild(menu);
    select.parentNode.insertBefore(wrapper, select.nextSibling);

    function syncCustomSelect() {
      const selectedOption = select.options[select.selectedIndex];
      const text = selectedOption ? selectedOption.textContent : 'Choose...';
      trigger.childNodes[0].textContent = text;
      
      if (select.disabled) {
        wrapper.classList.add('disabled');
      } else {
        wrapper.classList.remove('disabled');
      }

      menu.innerHTML = '';
      Array.from(select.options).forEach((opt) => {
        const item = document.createElement('div');
        item.className = 'custom-select-item';
        if (opt.value === select.value) {
          item.classList.add('selected');
        }
        item.textContent = opt.textContent;
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          if (select.disabled) return;
          select.value = opt.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          closeMenu();
        });
        menu.appendChild(item);
      });
    }

    syncCustomSelect();

    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      if (select.disabled) return;
      
      const isOpen = !menu.classList.contains('hidden');
      closeAllMenus();
      if (!isOpen) {
        menu.classList.remove('hidden');
        wrapper.classList.add('open');
      }
    });

    function closeMenu() {
      menu.classList.add('hidden');
      wrapper.classList.remove('open');
    }

    select.addEventListener('change', syncCustomSelect);

    const optObserver = new MutationObserver(() => {
      syncCustomSelect();
    });
    optObserver.observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'value'] });
  }

  function closeAllMenus() {
    document.querySelectorAll('.custom-select-menu').forEach(m => m.classList.add('hidden'));
    document.querySelectorAll('.custom-select-wrapper').forEach(w => w.classList.remove('open'));
  }

  document.addEventListener('click', closeAllMenus);

  function scanSelects() {
    document.querySelectorAll('select.restored-sel').forEach(initCustomSelect);
  }

  // Initial scan
  scanSelects();

  // Watch for dynamic selects added (e.g., in templates cloned via addCard)
  const bodyObserver = new MutationObserver((mutations) => {
    mutations.forEach(mutation => {
      mutation.addedNodes.forEach(node => {
        if (node.nodeType === Node.ELEMENT_NODE) {
          if (node.matches && node.matches('select.restored-sel')) {
            initCustomSelect(node);
          } else if (node.querySelectorAll) {
            node.querySelectorAll('select.restored-sel').forEach(initCustomSelect);
          }
        }
      });
    });
  });
  bodyObserver.observe(document.body, { childList: true, subtree: true });

  /* ── Filter brands by clothing type ── */
  const brandCache = new WeakMap();
  function cacheBrands(sel) {
    if (!brandCache.has(sel)) brandCache.set(sel, Array.from(sel.options).map(o => new Option(o.text, o.value)));
  }
  function matInDisabled(inp, disabled) {
    inp.disabled = disabled;
    inp.placeholder = disabled ? 'Please select a brand and clothing type' : 'Search materials...';
  }
  function initTypeSel(typeSel) {
    const card = typeSel.closest('.restored-card');
    const brandSel = card?.querySelector('.brand-sel');
    const matIn = card?.querySelector('.mat-in');
    if (!brandSel) return;
    cacheBrands(brandSel);
    if (!typeSel.value) {
      brandSel.disabled = true;
      brandSel.dispatchEvent(new Event('change', { bubbles: true }));
      if (matIn) matInDisabled(matIn, true);
    } else {
      filterBrandsByType(typeSel.value, brandSel, matIn, card, true);
    }
  }
  async function filterBrandsByType(type, brandSel, mIn, card, fromInit) {
    const allBrands = brandCache.get(brandSel);
    if (!allBrands) return;
    const prevVal = brandSel.value;
    if (!type) {
      brandSel.innerHTML = '';
      allBrands.forEach(o => brandSel.add(o.cloneNode(true)));
      brandSel.disabled = true;
      if (!fromInit) brandSel.dispatchEvent(new Event('change', { bubbles: true }));
      if (mIn) matInDisabled(mIn, true);
      return;
    }
    try {
      const res = await fetch(`/api/materials/search/?clothing_type=${type}`);
      if (!res.ok) return;
      const materials = await res.json();
      const validBrands = new Set(materials.map(m => m.brand));
      brandSel.innerHTML = '';
      allBrands.forEach(o => {
        if (!o.value || validBrands.has(o.value)) brandSel.add(o.cloneNode(true));
      });
      if (prevVal && validBrands.has(prevVal)) {
        brandSel.value = prevVal;
      } else {
        brandSel.value = '';
        if (mIn) { mIn.value = ''; matInDisabled(mIn, true); }
        const li = card?.querySelector('.lookup-id');
        if (li) li.value = '';
      }
      if (!fromInit) brandSel.dispatchEvent(new Event('change', { bubbles: true }));
    } catch { /* sequential logic controls disabled state */ }
  }

  /* ── Sequential field gating ── */
  function initSeqFields(card) {
    if (!card?.querySelector('.type-sel')) return;
    const type = card.querySelector('.type-sel');
    const weight = card.querySelector('.weight-in');
    const cond = card.querySelector('.cond-sel');
    const brand = card.querySelector('.brand-sel');
    if (weight) weight.disabled = !type.value;
    if (cond) cond.disabled = !weight?.value || weight?.disabled;
    if (brand && !type.value) brand.disabled = true;
    else if (brand && cond) brand.disabled = !cond.value || cond.disabled;
  }

  document.querySelectorAll('.brand-sel').forEach(cacheBrands);
  document.querySelectorAll('.type-sel').forEach(initTypeSel);
  document.querySelectorAll('.restored-card').forEach(initSeqFields);

  /* ── Observe new cards for brand filtering + seq fields ── */
  const cardBodyObs = new MutationObserver((muts) => {
    muts.forEach(m => m.addedNodes.forEach(n => {
      if (n.nodeType !== Node.ELEMENT_NODE) return;
      (n.matches && n.matches('.type-sel') ? [n] : (n.querySelectorAll ? n.querySelectorAll('.type-sel') : [])).forEach(ts => {
        initTypeSel(ts);
        initSeqFields(ts.closest('.restored-card'));
      });
    }));
  });
  cardBodyObs.observe(document.body, { childList: true, subtree: true });

  /* ── Type → Weight ── */
  document.addEventListener('change', (e) => {
    const sel = e.target.closest('.type-sel');
    if (!sel) return;
    const card = sel.closest('.restored-card');
    if (!card) return;
    const weight = card.querySelector('.weight-in');
    if (weight && sel.value) weight.disabled = false;
    const brandSel = card.querySelector('.brand-sel');
    if (!brandSel) return;
    cacheBrands(brandSel);
    filterBrandsByType(sel.value, brandSel, card.querySelector('.mat-in'), card);
  }, true);

  /* ── Weight → Condition → Brand ── */
  document.addEventListener('input', (e) => {
    if (!e.target.matches('.weight-in')) return;
    const card = e.target.closest('.restored-card');
    const cond = card?.querySelector('.cond-sel');
    if (!cond || !e.target.value) return;
    cond.disabled = false;
    if (cond.value) {
      const brandSel = card.querySelector('.brand-sel');
      if (!brandSel) return;
      brandSel.disabled = false;
      const type = card.querySelector('.type-sel')?.value;
      if (type) filterBrandsByType(type, brandSel, card.querySelector('.mat-in'), card);
    }
  });

  /* ── Condition → Brand ── */
  document.addEventListener('change', (e) => {
    if (!e.target.matches('.cond-sel')) return;
    const card = e.target.closest('.restored-card');
    if (!card) return;
    const brandSel = card.querySelector('.brand-sel');
    if (!brandSel || !e.target.value) return;
    brandSel.disabled = false;
    const type = card.querySelector('.type-sel')?.value;
    const matIn = card.querySelector('.mat-in');
    if (type) filterBrandsByType(type, brandSel, matIn, card);
  });
})();
