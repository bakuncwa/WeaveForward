(function() {
  if (localStorage.getItem('wf_tour_done_donor')) return;

  window.__wfTourActive = true;
  var isMobile = window.innerWidth < 768;

  var steps = [
    { target: '.filter-row', title: 'Filters', desc: 'Search by textile category or location to find businesses near you.' },
    { target: '.biz-card', fallback: '#biz-list', title: 'Businesses', desc: 'Textile upcycling businesses near you. Tap a card to view their cause and details.' },
    { target: '#nav-browse', title: 'Browse Businesses', desc: 'You are here — find businesses to donate to.' },
    { target: '#nav-donations', title: 'My Donations', desc: 'Create and manage all your donations here.' },
    { target: '#nav-dashboard', title: 'Impact Dashboard', desc: 'See your donation statistics and impact at a glance.' },
  ];

  var currentStep = 0;
  var spotlight, card;
  var currentEl = null;
  var rafId = null;
  var navStart = 2;
  var hadDummyCards = false;

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
    return document.querySelector(step.target) || (step.fallback ? document.querySelector(step.fallback) : null);
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

  function ensureBizCards() {
    if (document.querySelector('.biz-card')) return;
    var list = document.getElementById('biz-list');
    if (!list) return;
    hadDummyCards = true;
    var cards = [
      { name: 'EcoWeave Manila', loc: 'Makati City', tags: ['Cotton', 'Denim'], desc: 'Upcycles denim into bags and home decor.' },
      { name: 'Seda Recycle', loc: 'Quezon City', tags: ['Silk', 'Linen'], desc: 'Handcrafts silk scarves and linen garments.' },
    ];
    var html = '';
    for (var i = 0; i < cards.length; i++) {
      var c = cards[i];
      html += '<a class="biz-card" href="#" style="opacity:0.4;pointer-events:none">'
        + '<div class="biz-avatar" style="display:flex;align-items:center;justify-content:center;background:#eee;color:#aaa">'
        + '<svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">'
        + '<path d="M3 21h18M3 7v1a3 3 0 0 0 6 0V7m0 1a3 3 0 0 0 6 0V7m0 1a3 3 0 0 0 6 0V7H3m2 4h14v10H5V11z"/></svg></div>'
        + '<div class="biz-info"><div class="biz-name">' + c.name + '</div>'
        + '<div class="biz-loc"><svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">'
        + '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg> ' + c.loc + '</div>'
        + '<div class="biz-tags">';
      for (var j = 0; j < c.tags.length; j++) {
        html += '<span class="tag">' + c.tags[j] + '</span>';
      }
      html += '</div></div><div class="biz-desc">' + c.desc + '</div></a>';
    }
    var empty = list.querySelector('p');
    if (empty) empty.remove();
    list.insertAdjacentHTML('afterbegin', html);
  }

  function renderStep(index) {
    var step = steps[index];
    if (!step) return finish();

    if (!document.querySelector('.biz-card') && index === 1) ensureBizCards();

    var el = getTargetEl(step);
    currentEl = el;
    var total = steps.length;

    var sidebar = document.querySelector('#wf-sidebar-donor');
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
    window.__wfTourActive = false;
    localStorage.setItem('wf_tour_done_donor', 'true');
    if (rafId) cancelAnimationFrame(rafId);
    spotlight?.remove(); card?.remove();
    window.removeEventListener('scroll', onScroll, { passive: true, capture: true });
    var s = document.querySelector('#wf-sidebar-donor.open');
    if (s) { s.classList.remove('open'); document.getElementById('wf-overlay')?.classList.remove('open'); }
    if (window.__wfPendingGeo) window.__wfPendingGeo();
    if (hadDummyCards) location.reload();
  }

  createElements();
  window.addEventListener('scroll', onScroll, { passive: true, capture: true });

  if (document.readyState === 'complete') {
    renderStep(0);
  } else {
    window.addEventListener('load', function() { renderStep(0); });
  }
})();
