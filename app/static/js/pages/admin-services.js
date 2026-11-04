// Extracted from app/templates/admin/services.html — keep behaviour identical.
(function () {
  const orderDialog = document.querySelector('[data-service-order-dialog]');
  const archivedDialog = document.querySelector('[data-archived-services-dialog]');
  const orderList = document.querySelector('[data-service-order-list]');
  const scrollStorageKey = 'admin-services-scroll-position';

  function syncPageScrollLock() {
    const hasOpenDialog = Boolean(
      (orderDialog && orderDialog.hasAttribute('open')) ||
      (archivedDialog && archivedDialog.hasAttribute('open'))
    );

    document.body.classList.toggle('gallery-popup-open', hasOpenDialog);
  }

  function openDialog() {
    if (!orderDialog) {
      return;
    }

    if (typeof orderDialog.showModal === 'function') {
      orderDialog.showModal();
    } else {
      orderDialog.setAttribute('open', 'open');
    }

    syncPageScrollLock();
  }

  function closeDialog() {
    if (!orderDialog) {
      return;
    }

    if (orderDialog.open && typeof orderDialog.close === 'function') {
      orderDialog.close();
    } else {
      orderDialog.removeAttribute('open');
    }

    syncPageScrollLock();
  }

  function openArchivedDialog() {
    if (!archivedDialog) {
      return;
    }

    if (typeof archivedDialog.showModal === 'function') {
      archivedDialog.showModal();
    } else {
      archivedDialog.setAttribute('open', 'open');
    }

    syncPageScrollLock();
  }

  function closeArchivedDialog() {
    if (!archivedDialog) {
      return;
    }

    if (archivedDialog.open && typeof archivedDialog.close === 'function') {
      archivedDialog.close();
    } else {
      archivedDialog.removeAttribute('open');
    }

    syncPageScrollLock();
  }

  function restoreScrollPosition() {
    if (!window.sessionStorage) {
      return;
    }

    const saved = window.sessionStorage.getItem(scrollStorageKey);
    if (!saved) {
      return;
    }

    const position = Number(saved);
    if (!Number.isNaN(position)) {
      window.requestAnimationFrame(function () {
        window.scrollTo(0, position);
      });
    }

    window.sessionStorage.removeItem(scrollStorageKey);
  }

  function saveScrollPosition() {
    if (!window.sessionStorage) {
      return;
    }

    window.sessionStorage.setItem(scrollStorageKey, String(window.scrollY || window.pageYOffset || 0));
  }

  function refreshOrderList() {
    if (!orderList) {
      return;
    }

    const items = Array.from(orderList.querySelectorAll('[data-service-order-item]'));
    items.forEach(function (item, index) {
      const position = item.querySelector('[data-service-order-position]');
      const moveUpButton = item.querySelector('[data-service-move="up"]');
      const moveDownButton = item.querySelector('[data-service-move="down"]');

      if (position) {
        position.textContent = 'Position ' + (index + 1);
      }

      if (moveUpButton) {
        moveUpButton.disabled = index === 0;
      }

      if (moveDownButton) {
        moveDownButton.disabled = index === items.length - 1;
      }
    });
  }

  document.querySelectorAll('[data-service-order-open]').forEach(function (button) {
    button.addEventListener('click', openDialog);
  });

  document.querySelectorAll('[data-archived-services-open]').forEach(function (button) {
    button.addEventListener('click', openArchivedDialog);
  });

  document.querySelectorAll('[data-save-scroll-on-submit]').forEach(function (form) {
    form.addEventListener('submit', saveScrollPosition);
  });

  restoreScrollPosition();

  if (orderDialog) {
    orderDialog.querySelectorAll('[data-service-order-close]').forEach(function (button) {
      button.addEventListener('click', closeDialog);
    });

    orderDialog.addEventListener('click', function (event) {
      if (event.target === orderDialog) {
        closeDialog();
      }
    });

    orderDialog.addEventListener('cancel', function (event) {
      event.preventDefault();
      closeDialog();
    });

    orderDialog.addEventListener('close', syncPageScrollLock);
  }

  if (archivedDialog) {
    archivedDialog.querySelectorAll('[data-archived-services-close]').forEach(function (button) {
      button.addEventListener('click', closeArchivedDialog);
    });

    archivedDialog.addEventListener('click', function (event) {
      if (event.target === archivedDialog) {
        closeArchivedDialog();
      }
    });

    archivedDialog.addEventListener('cancel', function (event) {
      event.preventDefault();
      closeArchivedDialog();
    });

    archivedDialog.addEventListener('close', syncPageScrollLock);
  }

  if (orderList) {
    orderList.addEventListener('click', function (event) {
      const button = event.target.closest('[data-service-move]');
      if (!button) {
        return;
      }

      const item = button.closest('[data-service-order-item]');
      if (!item) {
        return;
      }

      if (button.dataset.serviceMove === 'up' && item.previousElementSibling) {
        orderList.insertBefore(item, item.previousElementSibling);
      }

      if (button.dataset.serviceMove === 'down' && item.nextElementSibling) {
        orderList.insertBefore(item.nextElementSibling, item);
      }

      refreshOrderList();
    });

    refreshOrderList();
  }

  syncPageScrollLock();
})();
