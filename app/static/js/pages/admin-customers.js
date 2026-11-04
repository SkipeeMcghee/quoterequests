// Extracted from app/templates/admin/customers.html — keep behaviour identical.
(function () {
  'use strict';

  var table = document.querySelector('.customer-list-table');
  var tbody = table ? table.querySelector('tbody') : null;
  var searchInput = document.getElementById('customer-filter-input');
  var helperText = document.querySelector('.admin-page-header__description');
  var emptyRow = document.getElementById('customer-filter-empty');
  var filterModal = document.getElementById('customer-filter-modal');
  var filterOpenBtn = document.getElementById('customer-filter-open');
  var filterCloseBtn = document.getElementById('customer-filter-modal-close');
  var filterForm = document.getElementById('customer-filter-form');
  var filterResetBtn = document.getElementById('customer-filter-reset');
  var filterIndicator = document.getElementById('customer-filter-indicator');
  var filterClearBtn = document.getElementById('customer-filter-clear');
  var sortBtns = Array.from(document.querySelectorAll('.rq-sort-btn[data-sort-field]'));

  if (!table || !tbody || !searchInput || !helperText || !emptyRow) {
    return;
  }

  var originalRows = Array.from(tbody.querySelectorAll('tr[data-customer-row]'));
  if (!originalRows.length) {
    var filterBar = document.querySelector('.rq-filter-bar');
    if (filterBar) {
      filterBar.hidden = true;
    }
    return;
  }

  var quickSortCycles = {
    customer: ['asc', 'desc', null],
    phone: ['asc', 'desc', null],
    email: ['asc', 'desc', null],
    billing: ['desc', 'asc', null]
  };

  var state = {
    activeFilters: {
      query: '',
      city: '',
      hasPhone: false,
      hasEmail: false,
      hasBilling: false
    },
    activeSort: {
      field: null,
      direction: null
    },
    isModified: false
  };

  function hasActiveSort() {
    return !!state.activeSort.field && !!state.activeSort.direction;
  }

  function hasActiveFilters() {
    var filters = state.activeFilters;
    return !!filters.query || !!filters.city || filters.hasPhone || filters.hasEmail || filters.hasBilling;
  }

  function syncToForm() {
    if (!filterForm) {
      return;
    }
    var cityInput = document.getElementById('customer-city-input');
    if (cityInput) {
      cityInput.value = state.activeFilters.city;
    }
    var phoneCheckbox = filterForm.querySelector('input[name="has-phone"]');
    if (phoneCheckbox) {
      phoneCheckbox.checked = state.activeFilters.hasPhone;
    }
    var emailCheckbox = filterForm.querySelector('input[name="has-email"]');
    if (emailCheckbox) {
      emailCheckbox.checked = state.activeFilters.hasEmail;
    }
    var billingCheckbox = filterForm.querySelector('input[name="has-billing"]');
    if (billingCheckbox) {
      billingCheckbox.checked = state.activeFilters.hasBilling;
    }
    var sortField = document.getElementById('customer-sort-field');
    if (sortField) {
      sortField.value = state.activeSort.field || '';
    }
    var sortDir = document.getElementById('customer-sort-dir');
    if (sortDir) {
      sortDir.value = state.activeSort.direction || 'desc';
    }
  }

  function collectFromForm() {
    if (!filterForm) {
      return;
    }
    var cityInput = document.getElementById('customer-city-input');
    state.activeFilters.city = cityInput ? cityInput.value.trim().toLowerCase() : '';
    var phoneCheckbox = filterForm.querySelector('input[name="has-phone"]');
    state.activeFilters.hasPhone = !!(phoneCheckbox && phoneCheckbox.checked);
    var emailCheckbox = filterForm.querySelector('input[name="has-email"]');
    state.activeFilters.hasEmail = !!(emailCheckbox && emailCheckbox.checked);
    var billingCheckbox = filterForm.querySelector('input[name="has-billing"]');
    state.activeFilters.hasBilling = !!(billingCheckbox && billingCheckbox.checked);

    var sortField = document.getElementById('customer-sort-field');
    var sortDir = document.getElementById('customer-sort-dir');
    state.activeSort.field = sortField ? (sortField.value || null) : null;
    state.activeSort.direction = state.activeSort.field ? (sortDir ? (sortDir.value || 'desc') : 'desc') : null;
  }

  function getSortValue(row, field) {
    if (field === 'customer') {
      return row.dataset.sortCustomer || '';
    }
    if (field === 'phone') {
      return Number(row.dataset.sortPhone || '0');
    }
    if (field === 'email') {
      return row.dataset.sortEmail || '';
    }
    if (field === 'billing') {
      return Number(row.dataset.sortBilling || '-1');
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

  function updateSortButtons() {
    sortBtns.forEach(function (btn) {
      var field = btn.dataset.sortField;
      var header = btn.closest('th');
      if (state.activeSort.field === field && state.activeSort.direction) {
        btn.dataset.sortActive = state.activeSort.direction;
        btn.setAttribute('aria-pressed', 'true');
        if (header) {
          header.setAttribute('aria-sort', state.activeSort.direction === 'asc' ? 'ascending' : 'descending');
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
    state.activeFilters.query = '';
    state.activeFilters.city = '';
    state.activeFilters.hasPhone = false;
    state.activeFilters.hasEmail = false;
    state.activeFilters.hasBilling = false;
    state.activeSort.field = null;
    state.activeSort.direction = null;
    searchInput.value = '';
    syncToForm();
    render();
  }

  function render() {
    var rows = originalRows.slice();
    var filters = state.activeFilters;

    if (filters.query) {
      rows = rows.filter(function (row) {
        return (row.textContent || '').toLowerCase().indexOf(filters.query) !== -1;
      });
    }

    if (filters.city) {
      rows = rows.filter(function (row) {
        return (row.dataset.filterCity || '').indexOf(filters.city) !== -1;
      });
    }

    if (filters.hasPhone) {
      rows = rows.filter(function (row) {
        return row.dataset.filterHasPhone === '1';
      });
    }

    if (filters.hasEmail) {
      rows = rows.filter(function (row) {
        return row.dataset.filterHasEmail === '1';
      });
    }

    if (filters.hasBilling) {
      rows = rows.filter(function (row) {
        return row.dataset.filterHasBilling === '1';
      });
    }

    if (hasActiveSort()) {
      var direction = state.activeSort.direction === 'asc' ? 1 : -1;
      var sortField = state.activeSort.field;

      rows = rows.slice().sort(function (a, b) {
        var aValue = getSortValue(a, sortField);
        var bValue = getSortValue(b, sortField);
        if (aValue < bValue) {
          return -direction;
        }
        if (aValue > bValue) {
          return direction;
        }
        return getOriginalIndex(a) - getOriginalIndex(b);
      });
    }

    while (tbody.firstChild) {
      tbody.removeChild(tbody.firstChild);
    }

    if (rows.length === 0) {
      emptyRow.hidden = false;
      tbody.appendChild(emptyRow);
    } else {
      emptyRow.hidden = true;
      rows.forEach(function (row) {
        tbody.appendChild(row);
      });
    }

    state.isModified = hasActiveFilters() || hasActiveSort();

    if (filterIndicator) {
      filterIndicator.hidden = !state.isModified;
    }

    helperText.textContent = rows.length + ' customer record' + (rows.length === 1 ? '' : 's');
    updateSortButtons();
  }

  originalRows.forEach(function (row) {
    row.addEventListener('click', function () {
      window.location.href = row.dataset.rowHref;
    });

    row.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') {
        return;
      }
      event.preventDefault();
      window.location.href = row.dataset.rowHref;
    });
  });

  searchInput.addEventListener('input', function () {
    state.activeFilters.query = searchInput.value.trim().toLowerCase();
    render();
  });

  sortBtns.forEach(function (btn) {
    btn.addEventListener('click', function (event) {
      event.stopPropagation();
      var nextSort = getNextQuickSortState(btn.dataset.sortField);
      state.activeSort.field = nextSort.field;
      state.activeSort.direction = nextSort.direction;
      syncToForm();
      render();
    });
  });

  function closeModal() {
    if (filterModal && filterModal.open) {
      filterModal.close();
    }
  }

  if (filterOpenBtn && filterModal && typeof filterModal.showModal === 'function') {
    filterOpenBtn.addEventListener('click', function () {
      syncToForm();
      filterModal.showModal();
    });
  }

  if (filterCloseBtn) {
    filterCloseBtn.addEventListener('click', closeModal);
  }

  if (filterModal) {
    filterModal.addEventListener('click', function (event) {
      if (event.target === filterModal) {
        closeModal();
      }
    });
  }

  if (filterForm) {
    filterForm.addEventListener('submit', function (event) {
      event.preventDefault();
      collectFromForm();
      render();
      closeModal();
    });
  }

  if (filterResetBtn) {
    filterResetBtn.addEventListener('click', function () {
      resetAll();
      closeModal();
    });
  }

  if (filterClearBtn) {
    filterClearBtn.addEventListener('click', resetAll);
  }

  render();
})();
