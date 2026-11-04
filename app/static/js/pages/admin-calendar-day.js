// Extracted from app/templates/admin/calendar_day.html — keep behaviour identical.
(function () {
  const calendarDayScrollKey = 'admin-calendar-day-scroll';

  function saveDayScroll(anchorId, destinationPath) {
    const target = anchorId ? document.getElementById(anchorId) : null;
    if (!target) {
      return;
    }

    try {
      sessionStorage.setItem(calendarDayScrollKey, JSON.stringify({
        anchorId,
        destinationPath: destinationPath || window.location.pathname,
        expiresAt: Date.now() + 15000,
        topOffset: target.getBoundingClientRect().top,
      }));
    } catch (error) {
      // Ignore storage failures and fall back to the browser default navigation.
    }
  }

  document.querySelectorAll('a[data-scroll-anchor]').forEach((link) => {
    link.addEventListener('click', function (event) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }

      saveDayScroll(link.dataset.scrollAnchor, link.pathname);
    });
  });

  try {
    const savedScrollState = sessionStorage.getItem(calendarDayScrollKey);
    if (!savedScrollState) {
      return;
    }

    sessionStorage.removeItem(calendarDayScrollKey);
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
    sessionStorage.removeItem(calendarDayScrollKey);
  }
})();
