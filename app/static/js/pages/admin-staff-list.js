// Extracted from app/templates/admin/staff_list.html — keep behaviour identical.
(function () {
  const summaries = Array.from(document.querySelectorAll('[data-service-summary]'));
  if (!summaries.length) {
    return;
  }

  const measurementHost = document.createElement('div');
  measurementHost.className = 'request-queue-service-summary request-queue-service-summary--measure';
  measurementHost.setAttribute('aria-hidden', 'true');
  measurementHost.innerHTML = [
    '<span class="request-queue-service-summary__text"></span>',
    '<span class="request-queue-service-summary__overflow"></span>',
  ].join('');
  document.body.appendChild(measurementHost);

  const measurementText = measurementHost.querySelector('.request-queue-service-summary__text');
  const measurementOverflow = measurementHost.querySelector('.request-queue-service-summary__overflow');

  function measureWidth(element, value) {
    element.textContent = value;
    return element.getBoundingClientRect().width;
  }

  function measureHeight(value, width) {
    measurementText.style.width = Math.max(width, 0) + 'px';
    measurementText.textContent = value;
    return measurementText.getBoundingClientRect().height;
  }

  function updateSummary(summary) {
    const textNode = summary.querySelector('[data-service-summary-text]');
    const overflowNode = summary.querySelector('[data-service-summary-overflow]');
    if (!textNode || !overflowNode) {
      return;
    }

    let services;
    try {
      services = JSON.parse(summary.dataset.services || '[]');
    } catch (error) {
      services = [];
    }

    if (!Array.isArray(services) || !services.length) {
      return;
    }

    const fullText = services.join(', ');
    const availableWidth = summary.getBoundingClientRect().width;
    const lineHeight = parseFloat(window.getComputedStyle(textNode).lineHeight || '0');
    const maxTextHeight = lineHeight * 2 + 1;

    textNode.textContent = fullText;
    overflowNode.textContent = '';
    overflowNode.hidden = true;
    summary.classList.remove('request-queue-service-summary--has-overflow');
    summary.style.removeProperty('--request-queue-overflow-width');

    if (!availableWidth || !lineHeight || measureHeight(fullText, availableWidth) <= maxTextHeight || services.length === 1) {
      return;
    }

    for (let visibleCount = services.length - 1; visibleCount >= 1; visibleCount -= 1) {
      const hiddenCount = services.length - visibleCount;
      const summaryText = services.slice(0, visibleCount).join(', ') + ', …';
      const overflowText = '+' + hiddenCount;
      const overflowWidth = measureWidth(measurementOverflow, overflowText);
      const remainingWidth = availableWidth - overflowWidth - 8;

      if (remainingWidth > 0 && measureHeight(summaryText, remainingWidth) <= maxTextHeight) {
        textNode.textContent = summaryText;
        overflowNode.textContent = overflowText;
        overflowNode.hidden = false;
        summary.classList.add('request-queue-service-summary--has-overflow');
        summary.style.setProperty('--request-queue-overflow-width', overflowWidth + 'px');
        return;
      }
    }

    textNode.textContent = '…';
    overflowNode.textContent = '+' + services.length;
    overflowNode.hidden = false;
    summary.classList.add('request-queue-service-summary--has-overflow');
    summary.style.setProperty('--request-queue-overflow-width', measureWidth(measurementOverflow, overflowNode.textContent) + 'px');
  }

  const refreshSummaries = function () {
    summaries.forEach(updateSummary);
  };

  refreshSummaries();

  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(function (entries) {
      entries.forEach(function (entry) {
        updateSummary(entry.target);
      });
    });

    summaries.forEach(function (summary) {
      observer.observe(summary);
    });
    return;
  }

  window.addEventListener('resize', refreshSummaries);
})();
