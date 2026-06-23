(function() {
  if (localStorage.getItem('wf_tour_done')) return;

  var isMobile = window.innerWidth < 768;

  var steps = [
    { target: '#tuab-dash-map', title: 'Map', desc: 'Each donation appears as a marker. Click a marker to preview, or click a table row to zoom to it.' },
    { target: '#dash-table-wrap', title: 'Donation List', desc: 'Every available donation is listed here as a row with the key details you need.' },
    { target: '.tuab-dashboard-table th:nth-child(2)', title: 'Donor Name', desc: 'See who donated so you know who you\'d coordinate with.' },
    { target: '.tuab-dashboard-table th:nth-child(3)', title: 'Address', desc: 'Where the donation is located — decide if it\'s within your service area.' },
    { target: '.tuab-dashboard-table th:nth-child(4)', title: 'Pick-Up Date', desc: 'When the donor wants the items picked up.' },
    { target: '.tuab-dashboard-table th:nth-child(5)', title: 'Items', desc: 'How many clothing items are in the donation.' },
    { target: '.tuab-dashboard-table .btn-tuab', title: 'Claim', desc: 'Click to view the full donation and choose to claim it.' },
    { target: '.btn-flag', title: 'Flag', desc: 'Report a donation to admins if it looks suspicious.' },
    { target: '#tab-claimed', title: 'Claimed Tab', desc: 'Switch here to track and manage donations you\'ve already claimed.' },
    { target: '#tnav-dashboard', title: 'Dashboard', desc: 'The main dashboard — browse and claim donations.' },
    { target: '#tnav-fiber', title: 'Fiber-Match', desc: 'AI that tells you which donations suit your preferences.' },
    { target: '#tnav-inventory', title: 'Inventory Snapshots', desc: 'Donated items appear here once you log them as received.' },
    { target: '#tnav-circular', title: 'Circular Economy', desc: 'View your environmental impact and sustainability metrics.' },
    { target: '#tnav-premium', title: 'Subscription', desc: 'Subscribe to premium features here.' },
    { target: '#tnav-payments', title: 'Payments', desc: 'View your subscription payment history.' },
  ];

  var currentStep = 0;
  var spotlight, card;
  var currentEl = null;
  var rafId = null;
  var hadDummyTable = false;
  var navStart = 9;
  var sidebarOpening = false;

  function createElements() {
    spotlight = document.createElement('div');
    spotlight.className = 'wf-tour-spotlight wf-tour-hidden';
    card = document.createElement('div');
    card.className = 'wf-tour-card';
    document.body.append(spotlight, card);

    if (isMobile) {
      card.style.position = 'fixed';
      card.style.bottom = '0';
      card.style.left = '0';
      card.style.width = '100%';
      card.style.maxWidth = '100%';
      card.style.borderRadius = '16px 16px 0 0';
      card.style.padding = '20px 20px 24px';
      card.style.top = 'auto';
    }
  }

  function getTargetEl(step) {
    var el = document.querySelector(step.target);
    if (!el && step.fallback) {
      el = typeof step.fallback === 'function' ? step.fallback() : document.querySelector(step.fallback);
    }
    return el;
  }

  function positionCard(rect) {
    if (isMobile) return;

    var cw = 380, ch = card.offsetHeight || 300;
    var gap = 16, vw = window.innerWidth, vh = window.innerHeight;
    var left, top;

    if (rect) {
      left = Math.max(16, Math.min(rect.left + rect.width / 2 - cw / 2, vw - cw - 16));
      if (vh - rect.bottom >= ch + gap + 20) top = rect.bottom + gap;
      else if (rect.top >= ch + gap + 20) top = rect.top - ch - gap;
      else top = Math.max(16, (vh - ch) / 2);
    } else {
      left = Math.max(16, (vw - cw) / 2);
      top = Math.max(16, (vh - ch) / 2);
    }
    card.style.left = left + 'px';
    card.style.top = top + 'px';
  }

  function applySpotlight(el) {
    if (!el) { spotlight.classList.add('wf-tour-hidden'); return; }
    var r = el.getBoundingClientRect();
    spotlight.classList.remove('wf-tour-hidden');
    spotlight.style.left = (r.left - 6) + 'px';
    spotlight.style.top = (r.top - 6) + 'px';
    spotlight.style.width = (r.width + 12) + 'px';
    spotlight.style.height = (r.height + 12) + 'px';
    spotlight.style.boxShadow = '0 0 0 3px #e8a020, 0 4px 20px rgba(0,0,0,.2)';
  }

  function refreshPosition() {
    if (!currentEl) return;
    applySpotlight(currentEl);
    positionCard(currentEl.getBoundingClientRect());
  }

  function onScroll() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(refreshPosition);
  }

  function ensureTable() {
    if (document.querySelector('.tuab-dashboard-table')) return;
    var wrap = document.getElementById('dash-table-wrap');
    if (!wrap) return;
    hadDummyTable = true;
    var table = document.createElement('table');
    table.className = 'wf-table tuab-dashboard-table';
    table.innerHTML = '<thead><tr>'
      + '<th>Donation ID</th><th>Donor</th><th>Address</th><th>Preffered Pick-Up Date</th><th>Items</th><th>Actions</th>'
      + '</tr></thead><tbody>'
      + '<tr><td>1001</td><td>Maria Santos</td><td>123 Rizal St, Makati</td><td>2025-07-15</td><td>12</td><td><div class="tuab-dashboard-actions"><span class="btn btn-tuab">Claim</span><button class="btn-flag">Flag</button></div></td></tr>'
      + '<tr><td>1002</td><td>Juan Dela Cruz</td><td>456 Mabini Ave, Manila</td><td>2025-07-18</td><td>8</td><td><div class="tuab-dashboard-actions"><span class="btn btn-tuab">Claim</span><button class="btn-flag">Flag</button></div></td></tr>'
      + '</tbody>';
    var old = wrap.querySelector('p');
    if (old) old.remove();
    wrap.prepend(table);
  }

  function renderStep(index) {
    var step = steps[index];
    if (!step) return finish();

    var el = getTargetEl(step);
    if (!el && index >= 2 && index <= 7) {
      ensureTable();
      el = getTargetEl(step);
    }
    currentEl = el;
    var total = steps.length;

    var sidebar = document.querySelector('#wf-sidebar-tuab');
    var isSidebarStep = index >= navStart;
    var needsSidebar = sidebar && getComputedStyle(sidebar).position === 'fixed';

    if (needsSidebar && isSidebarStep) {
      var wasOpen = sidebar.classList.contains('open');
      sidebar.classList.add('open');
      document.getElementById('wf-overlay')?.classList.add('open');
      if (wasOpen) {
        positionAfterSidebar(el);
      } else {
        sidebar.addEventListener('transitionend', function onEnd() {
          sidebar.removeEventListener('transitionend', onEnd);
          positionAfterSidebar(el);
        });
      }
    } else {
      if (needsSidebar && !isSidebarStep) {
        sidebar.classList.remove('open');
        document.getElementById('wf-overlay')?.classList.remove('open');
      }
      positionAfterSidebar(el);
    }

    function positionAfterSidebar(target) {
      if (target) {
        window.scrollTo(0, 0);
        applySpotlight(target);
        positionCard(target.getBoundingClientRect());
        requestAnimationFrame(function() {
          target.scrollIntoView({ block: 'center', inline: 'center' });
          requestAnimationFrame(function() {
            applySpotlight(target);
            positionCard(target.getBoundingClientRect());
          });
        });
      } else {
        spotlight.classList.add('wf-tour-hidden');
        positionCard(null);
      }
    }

    card.innerHTML = [
      '<div class="wf-tour-step-num">Step ' + (index + 1) + ' of ' + total + '</div>',
      '<div class="wf-tour-title">' + step.title + '</div>',
      '<div class="wf-tour-desc">' + step.desc + '</div>',
      '<div class="wf-tour-actions">',
        '<button class="wf-tour-skip">Skip tour</button>',
        '<div class="wf-tour-nav">',
          (index > 0 ? '<button class="wf-tour-btn wf-tour-btn-prev">Back</button>' : ''),
          (index < total - 1
            ? '<button class="wf-tour-btn wf-tour-btn-next">Next</button>'
            : '<button class="wf-tour-btn wf-tour-btn-finish">Finish</button>'),
        '</div>',
      '</div>',
    ].join('');

    card.querySelector('.wf-tour-skip')?.addEventListener('click', finish);
    card.querySelector('.wf-tour-btn-prev')?.addEventListener('click', function() { goTo(index - 1); });
    card.querySelector('.wf-tour-btn-next')?.addEventListener('click', function() { goTo(index + 1); });
    card.querySelector('.wf-tour-btn-finish')?.addEventListener('click', finish);
  }

  function goTo(index) { currentStep = index; renderStep(currentStep); }

  function finish() {
    localStorage.setItem('wf_tour_done', 'true');
    if (rafId) cancelAnimationFrame(rafId);
    spotlight?.remove(); card?.remove();
    window.removeEventListener('scroll', onScroll, { passive: true, capture: true });
    var s = document.querySelector('#wf-sidebar-tuab.open');
    if (s) { s.classList.remove('open'); document.getElementById('wf-overlay')?.classList.remove('open'); }
    if (hadDummyTable) location.reload();
  }

  createElements();
  window.addEventListener('scroll', onScroll, { passive: true, capture: true });

  function start() {
    if (!document.querySelector('.tuab-dashboard-table')) ensureTable();
    renderStep(0);
  }

  if (document.readyState === 'complete') {
    start();
  } else {
    window.addEventListener('load', start);
  }
})();
