// Extracted from app/templates/admin/dashboard.html — keep behaviour identical.
(function () {
  const rows = Array.from(document.querySelectorAll('[data-row-href]'));
  const interactiveSelector = 'a, button, input, select, textarea, summary, label';

  rows.forEach(function (row) {
    row.addEventListener('click', function (event) {
      if (event.target instanceof Element && event.target.closest(interactiveSelector)) {
        return;
      }

      window.location.href = row.dataset.rowHref;
    });

    row.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' || event.target !== row) {
        return;
      }

      event.preventDefault();
      window.location.href = row.dataset.rowHref;
    });
  });

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

(function () {
  'use strict';

  var table = document.querySelector('.request-queue-table');
  var tbody = table ? table.querySelector('tbody') : null;
  if (!tbody) return;

  // Collect data rows (excludes server-rendered empty-state row)
  var originalRows = Array.from(tbody.querySelectorAll('tr[data-filter-status]'));
  if (!originalRows.length) {
    var fb = document.querySelector('.rq-filter-bar');
    if (fb) fb.hidden = true;
    return;
  }

  var filterModal = document.getElementById('rq-filter-modal');
  var filterOpenBtn = document.getElementById('rq-filter-open');
  var filterCloseBtn = document.getElementById('rq-filter-modal-close');
  var filterForm = document.getElementById('rq-filter-form');
  var filterResetBtn = document.getElementById('rq-filter-reset');
  var filterIndicator = document.getElementById('rq-filter-indicator');
  var filterClearBtn = document.getElementById('rq-filter-clear');
  var sortBtns = Array.from(document.querySelectorAll('.rq-sort-btn[data-sort-field]'));
  var colCount = table.querySelectorAll('colgroup col').length || 5;

  // Preserve the server-rendered order so reset restores it exactly.
  var originalData = originalRows.slice();
  var quickSortCycles = {
    customer: ['asc', 'desc', null],
    submitted: ['desc', 'asc', null]
  };

  var state = {
    originalData: originalData,
    activeFilters: {
      statuses: new Set(),
      types: new Set(),
      name: '',
      dateFrom: '',
      dateTo: '',
      services: new Set()
    },
    activeSort: {
      field: null,
      direction: null
    },
    isModified: false
  };

  // ── Populate services checkboxes from row data ───────────────────────
  (function () {
    var container = document.getElementById('rq-filter-services-checks');
    if (!container) return;
    var seen = new Set();
    var list = [];
    state.originalData.forEach(function (row) {
      var svcs = [];
      try { svcs = JSON.parse(row.dataset.filterServices || '[]'); } catch (e) {}
      svcs.forEach(function (s) { if (!seen.has(s)) { seen.add(s); list.push(s); } });
    });
    list.sort();
    if (!list.length) {
      var grp = document.getElementById('rq-filter-services-group');
      if (grp) grp.hidden = true;
      return;
    }
    list.forEach(function (svc) {
      var lbl = document.createElement('label');
      lbl.className = 'rq-filter-check';
      var cb = document.createElement('input');
      cb.type = 'checkbox'; cb.name = 'service'; cb.value = svc;
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode('\u00a0' + svc));
      container.appendChild(lbl);
    });
  }());

  // ── Helpers ──────────────────────────────────────────────────────────
  function isModifiedState() {
    return state.isModified;
  }

  function hasActiveSort() {
    return !!state.activeSort.field && !!state.activeSort.direction;
  }

  function matchesOriginalView(rows) {
    if (rows.length !== state.originalData.length) {
      return false;
    }

    return rows.every(function (row, index) {
      return row === state.originalData[index];
    });
  }

  function collectFromForm() {
    if (!filterForm) return;
    state.activeFilters.statuses = new Set(
      Array.from(filterForm.querySelectorAll('input[name="status"]:checked')).map(function (i) { return i.value; })
    );
    state.activeFilters.types = new Set(
      Array.from(filterForm.querySelectorAll('input[name="type"]:checked')).map(function (i) { return i.value; })
    );
    var nameEl = document.getElementById('rq-name-input');
    state.activeFilters.name = nameEl ? nameEl.value : '';
    var dfi = document.getElementById('rq-date-from-input');
    state.activeFilters.dateFrom = dfi ? dfi.value : '';
    var dti = document.getElementById('rq-date-to-input');
    state.activeFilters.dateTo = dti ? dti.value : '';
    state.activeFilters.services = new Set(
      Array.from(filterForm.querySelectorAll('input[name="service"]:checked')).map(function (i) { return i.value; })
    );
    var sfEl = document.getElementById('rq-sort-field');
    var sdEl = document.getElementById('rq-sort-dir');
    state.activeSort.field = sfEl ? (sfEl.value || null) : null;
    state.activeSort.direction = state.activeSort.field ? (sdEl ? (sdEl.value || 'desc') : 'desc') : null;
  }

  function syncToForm() {
    if (!filterForm) return;
    filterForm.querySelectorAll('input[name="status"]').forEach(function (cb) {
      cb.checked = state.activeFilters.statuses.has(cb.value);
    });
    filterForm.querySelectorAll('input[name="type"]').forEach(function (cb) {
      cb.checked = state.activeFilters.types.has(cb.value);
    });
    var nameEl = document.getElementById('rq-name-input');
    if (nameEl) nameEl.value = state.activeFilters.name;
    var dfi = document.getElementById('rq-date-from-input');
    if (dfi) dfi.value = state.activeFilters.dateFrom;
    var dti = document.getElementById('rq-date-to-input');
    if (dti) dti.value = state.activeFilters.dateTo;
    filterForm.querySelectorAll('input[name="service"]').forEach(function (cb) {
      cb.checked = state.activeFilters.services.has(cb.value);
    });
    var sfEl = document.getElementById('rq-sort-field');
    if (sfEl) sfEl.value = state.activeSort.field || '';
    var sdEl = document.getElementById('rq-sort-dir');
    if (sdEl) sdEl.value = state.activeSort.direction || 'desc';
  }

  function getSortValue(row, field) {
    if (field === 'customer') {
      return row.dataset.sortCustomer || '';
    }
    if (field === 'submitted') {
      return row.dataset.sortSubmitted || '';
    }
    if (field === 'status') {
      return row.dataset.sortStatus || '';
    }
    return '';
  }

  function getOriginalIndex(row) {
    return Number(row.dataset.originalIndex || '0');
  }

  function getNextQuickSortState(field) {
    var cycle = quickSortCycles[field] || ['asc', 'desc', null];
    if (state.activeSort.field !== field) {
      return {
        field: field,
        direction: cycle[0]
      };
    }

    var currentIndex = cycle.indexOf(state.activeSort.direction);
    var nextDirection = cycle[(currentIndex + 1) % cycle.length];
    return {
      field: nextDirection ? field : null,
      direction: nextDirection
    };
  }

  function render() {
    var filters = state.activeFilters;
    var activeSort = state.activeSort;
    var rows = state.originalData.slice();

    if (filters.statuses.size > 0) {
      rows = rows.filter(function (r) { return filters.statuses.has(r.dataset.filterStatus); });
    }
    if (filters.types.size > 0) {
      rows = rows.filter(function (r) { return filters.types.has(r.dataset.filterType); });
    }
    if (filters.name.trim()) {
      var q = filters.name.trim().toLowerCase();
      rows = rows.filter(function (r) { return (r.dataset.filterName || '').indexOf(q) !== -1; });
    }
    if (filters.dateFrom) {
      rows = rows.filter(function (r) { return (r.dataset.filterSubmitted || '') >= filters.dateFrom; });
    }
    if (filters.dateTo) {
      rows = rows.filter(function (r) { return (r.dataset.filterSubmitted || '') <= filters.dateTo; });
    }
    if (filters.services.size > 0) {
      rows = rows.filter(function (r) {
        var svcs = [];
        try { svcs = JSON.parse(r.dataset.filterServices || '[]'); } catch (e) {}
        return svcs.some(function (s) { return filters.services.has(s); });
      });
    }

    if (hasActiveSort()) {
      var dir = activeSort.direction === 'asc' ? 1 : -1;
      var sf = activeSort.field;
      rows = rows.slice().sort(function (a, b) {
        var av = getSortValue(a, sf);
        var bv = getSortValue(b, sf);
        if (av < bv) {
          return -dir;
        }
        if (av > bv) {
          return dir;
        }
        return getOriginalIndex(a) - getOriginalIndex(b);
      });
    }

    state.isModified = !matchesOriginalView(rows);

    while (tbody.firstChild) { tbody.removeChild(tbody.firstChild); }

    if (rows.length === 0) {
      var eRow = document.createElement('tr');
      var eCell = document.createElement('td');
      eCell.setAttribute('colspan', String(colCount));
      eCell.className = 'empty-state';
      eCell.textContent = 'No requests match the active filters.';
      eRow.appendChild(eCell);
      tbody.appendChild(eRow);
    } else {
      rows.forEach(function (r) { tbody.appendChild(r); });
    }

    if (filterIndicator) {
      filterIndicator.hidden = !isModifiedState();
    }

    sortBtns.forEach(function (btn) {
      var field = btn.dataset.sortField;
      var header = btn.closest('th');
      if (activeSort.field === field && activeSort.direction) {
        btn.dataset.sortActive = activeSort.direction;
        btn.setAttribute('aria-pressed', 'true');
        if (header) {
          header.setAttribute('aria-sort', activeSort.direction === 'asc' ? 'ascending' : 'descending');
        }
      } else {
        delete btn.dataset.sortActive;
        btn.setAttribute('aria-pressed', 'false');
        if (header) {
          header.setAttribute('aria-sort', 'none');
        }
      }
    });
  }

  function resetAll() {
    state.activeFilters.statuses = new Set();
    state.activeFilters.types = new Set();
    state.activeFilters.name = '';
    state.activeFilters.dateFrom = '';
    state.activeFilters.dateTo = '';
    state.activeFilters.services = new Set();
    state.activeSort.field = null;
    state.activeSort.direction = null;
    syncToForm();
    render();
  }

  // Customer: unsorted -> asc -> desc -> off. Submitted: unsorted -> desc -> asc -> off.
  sortBtns.forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var nextSort = getNextQuickSortState(btn.dataset.sortField);
      state.activeSort.field = nextSort.field;
      state.activeSort.direction = nextSort.direction;
      syncToForm();
      render();
    });
  });

  // ── Modal open ───────────────────────────────────────────────────────
  if (filterOpenBtn && filterModal && typeof filterModal.showModal === 'function') {
    filterOpenBtn.addEventListener('click', function () {
      syncToForm();
      filterModal.showModal();
    });
  }

  // ── Modal close ──────────────────────────────────────────────────────
  function closeModal() {
    if (filterModal && filterModal.open) filterModal.close();
  }
  if (filterCloseBtn) filterCloseBtn.addEventListener('click', closeModal);
  if (filterModal) {
    filterModal.addEventListener('click', function (e) {
      if (e.target === filterModal) closeModal();
    });
  }

  // ── Form submit (Apply filters) ──────────────────────────────────────
  if (filterForm) {
    filterForm.addEventListener('submit', function (e) {
      e.preventDefault();
      collectFromForm();
      render();
      closeModal();
    });
  }

  // ── Modal reset ──────────────────────────────────────────────────────
  if (filterResetBtn) {
    filterResetBtn.addEventListener('click', function () {
      resetAll();
      closeModal();
    });
  }

  // ── Clear indicator (reset from badge) ───────────────────────────────
  if (filterClearBtn) filterClearBtn.addEventListener('click', resetAll);

  render();

}());
