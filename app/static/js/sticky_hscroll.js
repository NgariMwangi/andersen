/**
 * Fixed horizontal scrollbar at the bottom of the viewport.
 * Lets a normal mouse (vertical wheel only) move wide tables sideways.
 */
(function () {
  'use strict';

  var SKIP_ROOT = '.messages-workspace, .chat-thread-page, .chat-inbox-page';
  var HOST_SELECTOR = [
    '.leave-list-table-scroll',
    '.leave-tracker-scroll',
    '.table-responsive',
    '.app-hscroll',
    '.leave-requests-table-wrap',
    '.p9-table-wrap'
  ].join(', ');
  var HOST_CLASS = 'app-hscroll-host';
  var STEP = 280;

  var root = null;
  var track = null;
  var inner = null;
  var btnLeft = null;
  var btnRight = null;
  var activeHost = null;
  var syncing = false;
  var rafId = 0;
  var updating = false;

  function disabledPage() {
    return !!document.querySelector(SKIP_ROOT);
  }

  function hasHorizontalOverflow(el) {
    return el && el.scrollWidth > el.clientWidth + 1;
  }

  function overflowXScrollable(el) {
    var ox = window.getComputedStyle(el).overflowX;
    return ox === 'auto' || ox === 'scroll' || ox === 'overlay';
  }

  function discoverHosts() {
    var hosts = [];
    var seen = new Set();
    var roots = document.querySelectorAll('.app-content, .modal.show');

    function addHost(el) {
      if (!el || seen.has(el) || !hasHorizontalOverflow(el)) {
        return;
      }
      seen.add(el);
      hosts.push(el);
    }

    roots.forEach(function (scope) {
      scope.querySelectorAll(HOST_SELECTOR).forEach(addHost);

      scope.querySelectorAll('table').forEach(function (table) {
        var el = table.parentElement;
        while (el && el !== scope && el !== document.body) {
          if (overflowXScrollable(el) && hasHorizontalOverflow(el)) {
            addHost(el);
            break;
          }
          el = el.parentElement;
        }
      });
    });

    return hosts;
  }

  function markHosts(hosts) {
    document.querySelectorAll('.' + HOST_CLASS).forEach(function (el) {
      if (hosts.indexOf(el) === -1) {
        el.classList.remove(HOST_CLASS);
      }
    });
    hosts.forEach(function (host) {
      host.classList.add(HOST_CLASS);
      if (!host.dataset.appHscrollBound) {
        host.dataset.appHscrollBound = '1';
        host.addEventListener('wheel', onWheel, { passive: false });
      }
    });
  }

  function pickActiveHost(hosts) {
    if (!hosts.length) {
      return null;
    }

    var focused = document.activeElement;
    if (focused) {
      for (var i = 0; i < hosts.length; i += 1) {
        if (hosts[i].contains(focused)) {
          return hosts[i];
        }
      }
    }

    var vh = window.innerHeight || document.documentElement.clientHeight;
    var best = null;
    var bestScore = -1;

    hosts.forEach(function (host) {
      var rect = host.getBoundingClientRect();
      if (rect.bottom <= 0 || rect.top >= vh) {
        return;
      }
      var visibleHeight = Math.min(rect.bottom, vh) - Math.max(rect.top, 0);
      if (visibleHeight <= 0) {
        return;
      }
      var overflow = host.scrollWidth - host.clientWidth;
      var score = visibleHeight * overflow;
      if (score > bestScore) {
        bestScore = score;
        best = host;
      }
    });

    return best || hosts[0];
  }

  function hideBar() {
    if (root) {
      root.hidden = true;
    }
    document.body.classList.remove('app-sticky-hscroll-active');
    activeHost = null;
  }

  function maxScroll(el) {
    return Math.max(0, el.scrollWidth - el.clientWidth);
  }

  function syncBarFromHost() {
    if (!track || !activeHost || syncing) {
      return;
    }
    var hostMax = maxScroll(activeHost);
    var barMax = maxScroll(track);
    if (hostMax <= 0 || barMax <= 0) {
      return;
    }
    syncing = true;
    track.scrollLeft = activeHost.scrollLeft * (barMax / hostMax);
    syncing = false;
    updateButtons();
  }

  function syncHostFromBar() {
    if (!track || !activeHost || syncing) {
      return;
    }
    var hostMax = maxScroll(activeHost);
    var barMax = maxScroll(track);
    if (hostMax <= 0 || barMax <= 0) {
      return;
    }
    syncing = true;
    activeHost.scrollLeft = track.scrollLeft * (hostMax / barMax);
    syncing = false;
    updateButtons();
  }

  function updateButtons() {
    if (!activeHost || !btnLeft || !btnRight) {
      return;
    }
    var left = activeHost.scrollLeft;
    var max = maxScroll(activeHost);
    btnLeft.disabled = left <= 1;
    btnRight.disabled = left >= max - 1;
  }

  function scrollByStep(dir) {
    if (!activeHost) {
      return;
    }
    activeHost.scrollLeft += dir * STEP;
    syncBarFromHost();
  }

  function updateBar() {
    if (!root || !track || !inner || disabledPage()) {
      hideBar();
      return;
    }

    updating = true;
    var hosts = discoverHosts();
    markHosts(hosts);
    activeHost = pickActiveHost(hosts);

    if (!activeHost || maxScroll(activeHost) <= 1) {
      hideBar();
      updating = false;
      return;
    }

    root.hidden = false;
    document.body.classList.add('app-sticky-hscroll-active');
    inner.style.width = (maxScroll(activeHost) + track.clientWidth) + 'px';
    syncBarFromHost();
    updating = false;
  }

  function scheduleUpdate() {
    if (rafId) {
      return;
    }
    rafId = window.requestAnimationFrame(function () {
      rafId = 0;
      updateBar();
    });
  }

  function onWheel(event) {
    if (!activeHost) {
      return;
    }

    var overBar = root && root.contains(event.target);
    var overHost = activeHost.contains(event.target);
    if (!overBar && !overHost) {
      return;
    }

    var dx = event.deltaX;
    if (event.shiftKey || overBar) {
      dx = dx || event.deltaY;
    }

    if (!dx) {
      return;
    }

    event.preventDefault();
    activeHost.scrollLeft += dx;
    syncBarFromHost();
  }

  function init() {
    if (disabledPage()) {
      return;
    }

    root = document.getElementById('appStickyHScroll');
    track = root ? root.querySelector('.app-sticky-hscroll-track') : null;
    inner = root ? root.querySelector('.app-sticky-hscroll-inner') : null;
    btnLeft = root ? root.querySelector('[data-hscroll="-1"]') : null;
    btnRight = root ? root.querySelector('[data-hscroll="1"]') : null;
    if (!root || !track || !inner) {
      return;
    }

    track.addEventListener('scroll', syncHostFromBar, { passive: true });
    root.addEventListener('wheel', onWheel, { passive: false });
    window.addEventListener('scroll', scheduleUpdate, { passive: true, capture: true });
    window.addEventListener('resize', scheduleUpdate, { passive: true });
    window.addEventListener('load', scheduleUpdate);
    document.addEventListener('scroll', function (event) {
      if (event.target === activeHost) {
        syncBarFromHost();
      }
    }, { passive: true, capture: true });
    document.addEventListener('focusin', scheduleUpdate);
    document.addEventListener('shown.bs.modal', scheduleUpdate);
    document.addEventListener('hidden.bs.modal', scheduleUpdate);

    if (btnLeft && btnRight) {
      btnLeft.addEventListener('click', function (event) {
        event.preventDefault();
        scrollByStep(-1);
      });
      btnRight.addEventListener('click', function (event) {
        event.preventDefault();
        scrollByStep(1);
      });
    }

    if (typeof MutationObserver !== 'undefined') {
      var observer = new MutationObserver(function () {
        if (!updating) {
          scheduleUpdate();
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }

    scheduleUpdate();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
