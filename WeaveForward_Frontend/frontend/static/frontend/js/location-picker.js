/**
 * WeaveForward - Location Picker Utility
 * Handles address autocomplete, map picker modal, and reverse geocoding.
 */

const getEl = id => document.getElementById(id);
let map, mrk, tmpLat, tmpLng, acTmr, acRes = [];
let activePrefix = '';

// 1. Search for addresses as you type (Nominatim API)
function srchAddr(v, prefix = '') {
  activePrefix = prefix;
  const acId = prefix ? prefix + '_ac' : 'ac';
  
  // Clear coordinates since the address text is being modified
  const latId = prefix ? prefix + '_lat' : 'lat';
  const lngId = prefix ? prefix + '_lng' : 'lng';
  const latEl = getEl(latId);
  const lngEl = getEl(lngId);
  if (latEl) latEl.value = '';
  if (lngEl) lngEl.value = '';

  if (v.length < 3) return getEl(acId).classList.add('hidden');
  clearTimeout(acTmr);
  acTmr = setTimeout(async () => {
    try {
      const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(v + ', Philippines')}&limit=5&countrycodes=ph`);
      acRes = await res.json();
      getEl(acId).innerHTML = acRes.map((r, i) => `<div class="ac-item" onmousedown="selAddr(${i})">${r.display_name}</div>`).join('');
      getEl(acId).classList.remove('hidden');
    } catch (e) { 
      console.error("Search failed", e); 
      getEl(acId).innerHTML = `<div style="padding:10px 14px; color:#d9534f; font-weight:500; font-size:12.5px;">Location resolution services are unavailable.</div>`;
      getEl(acId).classList.remove('hidden');
    }
  }, 350);
}

// 2. Select an address from the suggestions list
function selAddr(i) {
  const r = acRes[i];
  const addrId = activePrefix ? activePrefix + '_addr' : 'addr';
  const latId = activePrefix ? activePrefix + '_lat' : 'lat';
  const lngId = activePrefix ? activePrefix + '_lng' : 'lng';
  getEl(addrId).value = r.display_name;
  getEl(latId).value = (+r.lat).toFixed(7);
  getEl(lngId).value = (+r.lon).toFixed(7);
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
      setTimeout(() => map.invalidateSize(), 100);
    }
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
  const addrId = activePrefix ? activePrefix + '_addr' : 'addr';
  const latId = activePrefix ? activePrefix + '_lat' : 'lat';
  const lngId = activePrefix ? activePrefix + '_lng' : 'lng';
  
  getEl(latId).value = tmpLat.toFixed(7);
  getEl(lngId).value = tmpLng.toFixed(7);
  closeMap();
  
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${tmpLat}&lon=${tmpLng}`);
    const data = await res.json();
    if (data.display_name) {
      getEl(addrId).value = data.display_name;
    }
  } catch (e) { 
    console.error("Reverse geocode failed", e);
    if (typeof showFlash === 'function') {
      showFlash('Location resolution services are unavailable.', 'error');
    }
  }
}
