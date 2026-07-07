/* ── Custom Fiber Composition Editor ── */
/* Requires global ALL_FIBERS (array of fiber names) */

function selectCustomComposition(el) {
    const wrap = el.closest('.ss-wrap');
    const card = wrap.closest('.restored-card') || wrap.closest('.item-card') || wrap.closest('[data-item-index]');
    const editor = wrap.querySelector('.fiber-editor');
    wrap.querySelector('.ss-list').classList.add('hidden');
    wrap.classList.remove('open');
    wrap.querySelector('.mat-trigger').classList.add('disabled');
    wrap.querySelector('.mat-text').textContent = 'Custom composition';
    editor.classList.remove('hidden');
    editor.querySelector('.fiber-rows').innerHTML = '';
    editor.querySelector('.fiber-composition').value = '';
    if (card) card.setAttribute('data-changed', 'true');
    addFiberRow(editor.querySelector('.fiber-add-btn'));
}

function rebuildFiberOptions(editor) {
    const rows = editor.querySelectorAll('.fiber-row');
    const selected = {};
    rows.forEach(function(r) {
        const val = r.querySelector('select').value;
        if (val) selected[val] = r;
    });
    rows.forEach(function(r) {
        const sel = r.querySelector('select');
        const currentVal = sel.value;
        sel.innerHTML = '<option value="">Select fiber...</option>' +
            ALL_FIBERS.map(function(f) {
                const disabled = selected[f] && selected[f] !== r;
                return '<option value="' + f + '"' +
                    (f === currentVal ? ' selected' : '') +
                    (disabled ? ' disabled' : '') +
                    '>' + f.charAt(0).toUpperCase() + f.slice(1) + '</option>';
            }).join('');
    });
}

function addFiberRow(btn) {
    const editor = btn.closest('.fiber-editor');
    const rows = editor.querySelector('.fiber-rows');
    const row = document.createElement('div');
    row.className = 'fiber-row';
    const sel = document.createElement('select');
    sel.innerHTML = '<option value="">Select fiber...</option>' + ALL_FIBERS.map(function (f) { return '<option value="' + f + '">' + f.charAt(0).toUpperCase() + f.slice(1) + '</option>'; }).join('');
    sel.addEventListener('change', function () { updateFiberTotal(editor); rebuildFiberOptions(editor); });
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.inputMode = 'numeric';
    inp.min = '0';
    inp.max = '100';
    inp.placeholder = '%';
    inp.addEventListener('input', function () { this.value = this.value.replace(/\D/g, '').slice(0, 3); updateFiberTotal(editor); });
    inp.addEventListener('blur', function () { this.value = String(Number(this.value || 0)); updateFiberTotal(editor); });
    const rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'fiber-rm';
    rm.innerHTML = '&times;';
    rm.addEventListener('click', function () { row.remove(); updateFiberTotal(editor); rebuildFiberOptions(editor); });
    row.append(sel, inp, rm);
    rows.appendChild(row);
    updateFiberTotal(editor);
    rebuildFiberOptions(editor);
}

function cancelCustomComposition(btn) {
    const wrap = btn.closest('.ss-wrap');
    resetCustomMode(wrap);
    const card = wrap.closest('.restored-card') || wrap.closest('.item-card') || wrap.closest('[data-item-index]');
    const brand = card.querySelector('.brand-sel');
    wrap.querySelector('.lookup-id').value = '';
    wrap.querySelector('.mat-trigger').classList.remove('disabled');
    wrap.querySelector('.mat-text').textContent = brand && brand.value ? 'Search or leave empty if unknown' : 'Please enter a brand and clothing type';
    if (brand && brand.value) loadMaterials(brand, true);
    if (card) card.setAttribute('data-changed', 'true');
}

function updateFiberTotal(editor) {
    const rows = editor.querySelectorAll('.fiber-row');
    let total = 0;
    var comp = {};
    var hasNeg = false;
    var hasEmptyFiber = false;
    rows.forEach(function (r) {
        const fiber = r.querySelector('select').value;
        const raw = parseInt(r.querySelector('input').value, 10) || 0;
        if (raw < 0) { hasNeg = true; r.querySelector('input').value = 0; return; }
        if (!fiber && raw > 0) hasEmptyFiber = true;
        if (fiber && raw > 0) comp[fiber] = raw;
        total += raw;
    });
    if (hasNeg) return updateFiberTotal(editor);
    const sumEl = editor.querySelector('.fiber-sum');
    sumEl.textContent = total;
    const totalEl = editor.querySelector('.fiber-total');
    const valid = !hasEmptyFiber && total === 100;
    totalEl.className = 'fiber-total' + (valid ? ' ok' : ' err');
    editor.querySelector('.fiber-composition').value = Object.keys(comp).length ? JSON.stringify(comp) : '';
}
