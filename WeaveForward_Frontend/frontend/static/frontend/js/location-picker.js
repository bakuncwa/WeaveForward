/**
 * WeaveForward - Location Picker Utility
 * Handles address autocomplete, map picker modal, and reverse geocoding.
 */

const getEl = id => document.getElementById(id);
const escapeHTML = str => !str ? '' : str.replace(/[&<>'"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;' }[c] || c));
let map, mrk, tmpLat, tmpLng, acTmr, acRes = [];
let activePrefix = '';
let pendingLookups = 0;

function setSubmitDisabled(disabled) {
  var form = document.querySelector('form[id$="-frm"]');
  if (!form) return;
  var btn = form.querySelector('[type="submit"]');
  if (!btn) return;
  btn.disabled = disabled;
  btn.style.opacity = disabled ? '0.5' : '';
  btn.style.cursor = disabled ? 'not-allowed' : '';
}

function lockSubmit() {
  pendingLookups++;
  setSubmitDisabled(true);
}

function unlockSubmit() {
  pendingLookups--;
  if (pendingLookups < 0) pendingLookups = 0;
  if (pendingLookups === 0) setSubmitDisabled(false);
}

function releaseAllLocks() {
  pendingLookups = 0;
  setSubmitDisabled(false);
}

function setAddressValue(prefix, address) {
  const addrId = prefix ? prefix + '_addr' : 'addr';
  const textId = prefix ? prefix + '_addr-text' : 'addr-text';
  const addrEl = getEl(addrId);
  const textEl = getEl(textId);

  if (addrEl) {
    addrEl.value = address;
    addrEl.dispatchEvent(new Event('input', { bubbles: true }));
    addrEl.dispatchEvent(new Event('change', { bubbles: true }));
  }
  if (textEl) textEl.textContent = address || 'Address';
}

// 0. Toggle address dropdown (material pattern)
function toggleAddrDropdown(trigger) {
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
    const items = list.querySelector('.mat-items');
    if (items) items.innerHTML = '';
  }
}

// 1. Search for addresses as you type (Nominatim API)
function srchAddr(v, prefix = '') {
  activePrefix = prefix;
  const itemsId = prefix ? prefix + '_items' : 'addr-items';
  const acId = prefix ? prefix + '_ac' : 'ac';
  
  const latId = prefix ? prefix + '_lat' : 'lat';
  const lngId = prefix ? prefix + '_lng' : 'lng';
  const latEl = getEl(latId);
  const lngEl = getEl(lngId);
  if (latEl) latEl.value = '';
  if (lngEl) lngEl.value = '';

  if (v.length < 3) {
    getEl(itemsId).innerHTML = '';
    clearTimeout(acTmr);
    return;
  }
  clearTimeout(acTmr);
  acTmr = setTimeout(async () => {
    try {
      const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(v)}&limit=5&countrycodes=ph`);
      acRes = await res.json();
      getEl(itemsId).innerHTML = acRes.map((r, i) => `<div class="mat-item" onmousedown="event.preventDefault(); selAddr(${i})">${escapeHTML(r.display_name)}</div>`).join('');
      getEl(acId).classList.remove('hidden');
    } catch (e) { 
      console.error("Search failed", e); 
      getEl(itemsId).innerHTML = `<div style="padding:10px 14px; color:#d9534f; font-weight:500; font-size:12.5px;">Location resolution services are unavailable.</div>`;
      getEl(acId).classList.remove('hidden');
    }
  }, 350);
}

// 2. Select an address from the suggestions list
function selAddr(i) {
  const r = acRes[i];
  const prefix = activePrefix;
  const latId = prefix ? prefix + '_lat' : 'lat';
  const lngId = prefix ? prefix + '_lng' : 'lng';
  const textId = prefix ? prefix + '_addr-text' : 'addr-text';
  const acId = prefix ? prefix + '_ac' : 'ac';
  
  getEl(latId).value = (+r.lat).toFixed(7);
  getEl(lngId).value = (+r.lon).toFixed(7);
  setAddressValue(prefix, r.display_name);

  const textEl = getEl(textId);
  const acEl = getEl(acId);
  if (acEl) acEl.classList.add('hidden');
  
  const wrap = textEl ? textEl.closest('.ss-wrap') : null;
  if (wrap) wrap.classList.remove('open');
}

// 3. Open the Map Modal and initialize Leaflet if needed
function openMap(prefix = '') {
  activePrefix = prefix;
  getEl('map-modal').classList.remove('hidden');
  
  const latId = prefix ? prefix + '_lat' : 'lat';
  const lngId = prefix ? prefix + '_lng' : 'lng';
  const l = +getEl(latId).value || 14.5995, g = +getEl(lngId).value || 120.9842;
  tmpLat = l; tmpLng = g;
  
  if (typeof L === 'undefined') {
    showMapError();
    return;
  }
  
  try {
    if (!map) {
      map = L.map('picker-map').setView([l, g], 15);
      const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
      tiles.on('tileerror', showMapError);
      mrk = L.marker([l, g], { draggable: true }).addTo(map);
      
      mrk.on('dragend', e => { 
        const p = e.target.getLatLng(); 
        tmpLat = p.lat; 
        tmpLng = p.lng; 
      });
      
      map.on('click', e => { 
        tmpLat = e.latlng.lat; 
        tmpLng = e.latlng.lng; 
        mrk.setLatLng(e.latlng); 
      });
    } else {
      map.setView([l, g]); 
      mrk.setLatLng([l, g]);
    }
    setTimeout(() => map.invalidateSize(), 100);
  } catch (err) {
    showMapError();
  }
}

function showMapError() {
  const pm = getEl('picker-map');
  if (pm) {
    pm.style.height = 'auto';
    pm.innerHTML = `<div style="padding:40px 20px; text-align:center; color:#d9534f; font-weight:500; font-family:'Poppins',sans-serif;"><svg width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24" style="margin-bottom:12px; display:inline-block;"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" /></svg><p style="margin:0;">Map service is currently unavailable. Interactive map features have been disabled.</p></div>`;
  }
  const btn = document.querySelector('.map-confirm');
  if (btn) {
    btn.disabled = true;
    btn.style.opacity = '0.5';
    btn.style.cursor = 'not-allowed';
  }
}

// 4. Close the Map Modal
const closeMap = () => getEl('map-modal').classList.add('hidden');

// 5. Confirm the selection and perform reverse geocoding
async function confirmMap() {
  const prefix = activePrefix;
  const latId = activePrefix ? activePrefix + '_lat' : 'lat';
  const lngId = activePrefix ? activePrefix + '_lng' : 'lng';
  
  getEl(latId).value = tmpLat.toFixed(7);
  getEl(lngId).value = tmpLng.toFixed(7);
  closeMap();
  
  lockSubmit();
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${tmpLat}&lon=${tmpLng}`, {
      headers: { 'Accept-Language': 'en-US' }
    });
    if (!res.ok) throw new Error('Reverse geocode failed');
    const data = await res.json();
    if (data.display_name) {
      setAddressValue(prefix, data.display_name);
    } else {
      throw new Error('Missing display address');
    }
  } catch (e) { 
    console.error("Reverse geocode failed", e);
    setAddressValue(prefix, '');
    if (typeof showFlash === 'function') {
      showFlash('Could not resolve a display address. Search for the address or pick another map point.', 'error');
    } else {
      alert('Could not resolve a display address. Search for the address or pick another map point.');
    }
  } finally {
    unlockSubmit();
  }
}

document.addEventListener('click', e => {
  if (e.target === getEl('map-modal')) closeMap();
  if (!e.target.closest('.ss-wrap')) {
    document.querySelectorAll('.ss-list').forEach(l => l.classList.add('hidden'));
    document.querySelectorAll('.ss-wrap').forEach(w => w.classList.remove('open'));
  }
});
