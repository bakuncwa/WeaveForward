async function loadMaterials(el, preserve = false) {
  const card = el.closest('.restored-card');
  const typeSel = card.querySelector('.type-sel');
  const brandSel = card.querySelector('.brand-sel');
  const type = typeSel.value;
  const brand = brandSel.value;
  const wrap = card.querySelector('.mat-search-wrap');
  const trigger = wrap.querySelector('.mat-trigger');
  const matText = trigger.querySelector('.mat-text');
  const list = wrap.querySelector('.ss-list');
  const itemsContainer = wrap.querySelector('.mat-items');

  if (!preserve) {
    card.querySelector('.lookup-id').value = '';
  }
  list.classList.add('hidden');
  wrap.classList.remove('open');

  if (!type || !brand) {
    trigger.classList.add('disabled');
    if (!preserve) {
      if (!type && !brand) matText.textContent = 'Please enter a brand and clothing type';
      else if (!type) matText.textContent = 'Please enter a clothing type';
      else matText.textContent = 'Please enter a brand';
    }
    return;
  }

  try {
    const url = wrap.dataset.apiUrl;
    const res = await fetch(`${url}?clothing_type=${type}&brand=${brand}`);
    if (!res.ok) throw new Error("HTTP error " + res.status);
    const materials = await res.json();

    itemsContainer.innerHTML = '';
    if (!materials.length) {
      if (!preserve) {
        matText.textContent = 'We\'ll guess the material for you';
        trigger.classList.add('disabled');
      }
    } else {
      trigger.classList.remove('disabled');
      if (!preserve) matText.textContent = 'Search or leave empty if unknown';
      for (const m of materials) {
        const productName = m.product_name || '';
        const div = document.createElement('div');
        div.className = 'mat-item';
        const b = document.createElement('b');
        b.textContent = productName;
        div.append(b, document.createTextNode(' ' + (m.fiber_json || '')));
        div.dataset.lookupId = m.lookup_id;
        div.dataset.display = `${m.fiber_json} - ${productName}`;
        div.addEventListener('click', function () {
          selectMat(this, this.dataset.lookupId, this.dataset.display);
        });
        itemsContainer.appendChild(div);
      }
    }
  } catch (e) {
    console.error(e);
    showFlash("Donation records could not be retrieved.", "error");
  }
}

function selectMat(el, id, text) {
  const wrap = el.closest('.ss-wrap');
  wrap.querySelector('.mat-text').textContent = text;
  wrap.querySelector('.lookup-id').value = id;
  wrap.querySelector('.ss-list').classList.add('hidden');
  wrap.classList.remove('open');
  wrap.querySelector('.mat-trigger').classList.remove('disabled');
  wrap.closest('.restored-card')?.setAttribute('data-changed', 'true');
}

function clearMat(el) {
  const wrap = el.closest('.ss-wrap');
  const card = wrap.closest('.restored-card');
  wrap.querySelector('.mat-text').textContent = 'Search or leave empty if unknown';
  wrap.querySelector('.lookup-id').value = '';
  loadMaterials(card.querySelector('.brand-sel'));
  card?.setAttribute('data-changed', 'true');
}
