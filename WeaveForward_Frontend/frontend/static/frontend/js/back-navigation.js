(function () {
  const currentPath = window.location.pathname;
  const currentRoute = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const backRoutes = [
    {
      key: 'wfBack:tuab:donations',
      listPaths: ['/tuab/dashboard/', '/tuab/inventory/'],
      detailPrefixes: ['/tuab/donations/'],
      fallbackPath: '/tuab/dashboard/',
    },
    {
      key: 'wfBack:donor:donations',
      listPaths: ['/donor/my-donations/'],
      detailPrefixes: ['/donor/my-donations/', '/donor/create-donation/'],
      fallbackPath: '/donor/my-donations/',
    },
    {
      key: 'wfBack:donor:tuabs',
      listPaths: ['/donor/browse-businesses/', '/donor/my-donations/'],
      detailPrefixes: ['/donor/tuabs/'],
      fallbackPath: '/donor/browse-businesses/',
    },
    {
      key: 'wfBack:admin:donations',
      listPaths: ['/admin/donations/'],
      detailPrefixes: ['/admin/donations/'],
      fallbackPath: '/admin/donations/',
    },
    {
      key: 'wfBack:admin:donors',
      listPaths: ['/admin/donors/'],
      detailPrefixes: ['/admin/donors/'],
      fallbackPath: '/admin/donors/',
    },
    {
      key: 'wfBack:admin:tuabs',
      listPaths: ['/admin/tuabs/', '/admin/donations/'],
      detailPrefixes: ['/admin/tuabs/'],
      fallbackPath: '/admin/tuabs/',
    },
    {
      key: 'wfBack:tuab:profile',
      listPaths: ['/tuab/profile/'],
      detailPrefixes: ['/tuab/profile/edit/'],
      fallbackPath: '/tuab/profile/',
    },
    {
      key: 'wfBack:donor:profile',
      listPaths: ['/donor/profile/'],
      detailPrefixes: ['/donor/profile/edit/'],
      fallbackPath: '/donor/profile/',
    },
  ];

  function isSameOriginPath(value) {
    return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//');
  }

  function linkPath(anchor) {
    try {
      const url = new URL(anchor.getAttribute('href'), window.location.origin);
      if (url.origin !== window.location.origin) return null;
      return url.pathname;
    } catch {
      return null;
    }
  }

  function rememberRoute(key, value) {
    try {
      sessionStorage.setItem(key, value);
    } catch {}
  }

  function recallRoute(key) {
    try {
      return sessionStorage.getItem(key);
    } catch {
      return null;
    }
  }

  backRoutes.forEach(route => {
    if (route.listPaths.includes(currentPath)) {
      rememberRoute(route.key, currentRoute);
    }
  });

  const matchedBackRoute = backRoutes.find(route => (
    !route.listPaths.includes(currentPath)
    && route.detailPrefixes.some(prefix => currentPath.startsWith(prefix))
  ));

  if (matchedBackRoute) {
    const rememberedRoute = recallRoute(matchedBackRoute.key);
    const topbarBackButton = document.querySelector('.wf-back-btn');
    if (isSameOriginPath(rememberedRoute)) {
      const rewriteBackLink = anchor => {
        if (!anchor) return;
        if (anchor === topbarBackButton || linkPath(anchor) === matchedBackRoute.fallbackPath) {
          anchor.setAttribute('href', rememberedRoute);
          anchor.hidden = false;
        }
      };

      rewriteBackLink(topbarBackButton);
      document.querySelectorAll('.wf-content a[href]').forEach(rewriteBackLink);
    } else if (topbarBackButton) {
      topbarBackButton.hidden = true;
    }
  }
})();
