// Extracted from app/templates/admin/calendar.html — keep behaviour identical.
(function () {
  const scheduleScrollKey = 'admin-schedule-scroll';

  function saveScheduleScroll(anchorId, destinationPath) {
    const target = anchorId ? document.getElementById(anchorId) : null;
    if (!target) {
      return;
    }

    try {
      sessionStorage.setItem(scheduleScrollKey, JSON.stringify({
        anchorId,
        destinationPath: destinationPath || window.location.pathname,
        expiresAt: Date.now() + 15000,
        topOffset: target.getBoundingClientRect().top,
      }));
    } catch (error) {
      // Ignore storage issues and fall back to the browser's default navigation.
    }
  }

  document.querySelectorAll('a[data-scroll-anchor]').forEach((link) => {
    link.addEventListener('click', function (event) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }

      saveScheduleScroll(link.dataset.scrollAnchor, link.pathname);
    });
  });

  document.querySelectorAll('form[data-scroll-anchor]').forEach((form) => {
    form.addEventListener('submit', function () {
      saveScheduleScroll(form.dataset.scrollAnchor, window.location.pathname);
    });
  });

  const fitTextTargets = Array.from(document.querySelectorAll('[data-fit-text]'));

  function fitHeading(target) {
    const maxSize = parseFloat(target.dataset.fitMaxSize || '2.3');
    const minSize = parseFloat(target.dataset.fitMinSize || '1.35');
    const step = 0.05;
    let fontSize = maxSize;

    target.style.fontSize = fontSize + 'rem';
    while (target.scrollWidth > target.clientWidth + 1 && fontSize > minSize) {
      fontSize = Math.max(minSize, fontSize - step);
      target.style.fontSize = fontSize.toFixed(2) + 'rem';
    }
  }

  if (fitTextTargets.length) {
    const refreshFitTextTargets = function () {
      fitTextTargets.forEach(fitHeading);
    };

    refreshFitTextTargets();
    window.addEventListener('resize', refreshFitTextTargets);
  }

  try {
    const savedScrollState = sessionStorage.getItem(scheduleScrollKey);
    if (!savedScrollState) {
      return;
    }

    sessionStorage.removeItem(scheduleScrollKey);
    const scrollState = JSON.parse(savedScrollState);
    if (!scrollState || scrollState.destinationPath !== window.location.pathname || !scrollState.anchorId) {
      return;
    }

    if (scrollState.expiresAt && scrollState.expiresAt < Date.now()) {
      return;
    }

    const target = document.getElementById(scrollState.anchorId);
    if (!target) {
      return;
    }

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        const desiredTop = window.scrollY + target.getBoundingClientRect().top - (scrollState.topOffset || 0);
        window.scrollTo(0, Math.max(0, desiredTop));
      });
    });
  } catch (error) {
    sessionStorage.removeItem(scheduleScrollKey);
  }
})();
