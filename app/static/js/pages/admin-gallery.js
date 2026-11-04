// Extracted from app/templates/admin/gallery.html — keep behaviour identical.
(function () {
  const dialogs = Array.from(document.querySelectorAll('[data-gallery-dialog]'));
  const lightbox = document.getElementById('gallery-image-lightbox');
  const lightboxImage = lightbox ? lightbox.querySelector('[data-gallery-lightbox-image]') : null;
  const uploadDropzones = Array.from(document.querySelectorAll('[data-gallery-upload-dropzone]'));

  function syncPageScrollLock() {
    const hasOpenGalleryPopup = dialogs.some(function (dialog) {
      return dialog.hasAttribute('open');
    }) || (lightbox && lightbox.hasAttribute('open'));

    document.body.classList.toggle('gallery-popup-open', Boolean(hasOpenGalleryPopup));
  }

  function openDialog(dialog) {
    if (!dialog) {
      return;
    }

    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
      syncPageScrollLock();
      return;
    }

    dialog.setAttribute('open', 'open');
    syncPageScrollLock();
  }

  function closeDialog(dialog) {
    if (!dialog) {
      return;
    }

    if (dialog.open && typeof dialog.close === 'function') {
      dialog.close();
      syncPageScrollLock();
      return;
    }

    dialog.removeAttribute('open');
    syncPageScrollLock();
  }

  document.querySelectorAll('[data-gallery-modal-open]').forEach(function (button) {
    button.addEventListener('click', function () {
      openDialog(document.getElementById(button.dataset.galleryModalOpen));
    });
  });

  dialogs.forEach(function (dialog) {
    dialog.querySelectorAll('[data-gallery-modal-close]').forEach(function (button) {
      button.addEventListener('click', function () {
        closeDialog(dialog);
      });
    });

    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) {
        closeDialog(dialog);
      }
    });

    dialog.addEventListener('cancel', function (event) {
      event.preventDefault();
      closeDialog(dialog);
    });

    dialog.addEventListener('close', syncPageScrollLock);

    if (dialog.hasAttribute('data-open-on-load')) {
      openDialog(dialog);
    }
  });

  uploadDropzones.forEach(function (dropzone) {
    const input = dropzone.querySelector('.gallery-upload-dropzone__input');
    const filename = dropzone.querySelector('[data-gallery-upload-filename]');
    const surface = dropzone.querySelector('.gallery-upload-dropzone__surface');

    if (!input || !filename || !surface) {
      return;
    }

    function setFileLabel(files) {
      if (!files || !files.length) {
        filename.textContent = 'No file selected';
        return;
      }

      if (files.length === 1) {
        filename.textContent = files[0].name;
        return;
      }

      filename.textContent = files.length + ' files selected';
    }

    input.addEventListener('change', function () {
      setFileLabel(input.files);
    });

    ['dragenter', 'dragover'].forEach(function (eventName) {
      surface.addEventListener(eventName, function (event) {
        event.preventDefault();
        dropzone.classList.add('is-dragging');
      });
    });

    ['dragleave', 'dragend'].forEach(function (eventName) {
      surface.addEventListener(eventName, function (event) {
        if (event.relatedTarget && dropzone.contains(event.relatedTarget)) {
          return;
        }

        dropzone.classList.remove('is-dragging');
      });
    });

    surface.addEventListener('drop', function (event) {
      event.preventDefault();
      dropzone.classList.remove('is-dragging');

      const droppedFiles = event.dataTransfer ? event.dataTransfer.files : null;
      if (!droppedFiles || !droppedFiles.length) {
        return;
      }

      try {
        const transfer = new DataTransfer();
        Array.from(droppedFiles).forEach(function (file) {
          transfer.items.add(file);
        });
        input.files = transfer.files;
      } catch (error) {
        return;
      }

      setFileLabel(input.files);
    });
  });

  const orderList = document.querySelector('[data-gallery-order-list]');

  function refreshOrderList() {
    if (!orderList) {
      return;
    }

    const items = Array.from(orderList.querySelectorAll('[data-gallery-order-item]'));
    items.forEach(function (item, index) {
      const position = item.querySelector('[data-gallery-order-position]');
      const moveUpButton = item.querySelector('[data-gallery-move="up"]');
      const moveDownButton = item.querySelector('[data-gallery-move="down"]');
      const visibilityToggle = item.querySelector('input[name="visible_item_id"]');
      const visibilityLabel = item.querySelector('[data-gallery-visibility-label]');

      if (position) {
        position.textContent = 'Position ' + (index + 1);
      }

      if (moveUpButton) {
        moveUpButton.disabled = index === 0;
      }

      if (moveDownButton) {
        moveDownButton.disabled = index === items.length - 1;
      }

      if (visibilityToggle && visibilityLabel) {
        visibilityLabel.textContent = visibilityToggle.checked ? 'Visible' : 'Hidden';
      }
    });
  }

  if (orderList) {
    orderList.addEventListener('click', function (event) {
      const button = event.target.closest('[data-gallery-move]');
      if (!button) {
        return;
      }

      const item = button.closest('[data-gallery-order-item]');
      if (!item) {
        return;
      }

      if (button.dataset.galleryMove === 'up' && item.previousElementSibling) {
        orderList.insertBefore(item, item.previousElementSibling);
      }

      if (button.dataset.galleryMove === 'down' && item.nextElementSibling) {
        orderList.insertBefore(item.nextElementSibling, item);
      }

      refreshOrderList();
    });

    orderList.addEventListener('change', function (event) {
      if (event.target instanceof HTMLInputElement && event.target.name === 'visible_item_id') {
        refreshOrderList();
      }
    });

    refreshOrderList();
  }

  function setAutosaveStatus(form, message, isError) {
    const statusElement = form.querySelector('[data-gallery-autosave-status]');
    if (!statusElement) {
      return;
    }

    if (form._galleryStatusTimer) {
      window.clearTimeout(form._galleryStatusTimer);
      form._galleryStatusTimer = null;
    }

    statusElement.textContent = message || '';
    statusElement.dataset.state = message ? (isError ? 'error' : 'saved') : '';

    if (message && !isError) {
      form._galleryStatusTimer = window.setTimeout(function () {
        statusElement.textContent = '';
        statusElement.dataset.state = '';
      }, 1600);
    }
  }

  function applyAutosavePayload(form, payload) {
    if (!payload || !payload.item) {
      return;
    }

    const card = form.closest('.gallery-management-card');
    const featuredBadge = card ? card.querySelector('[data-gallery-featured-badge]') : null;
    const previewButton = card ? card.querySelector('[data-gallery-lightbox-open]') : null;
    const orderItem = document.querySelector('[data-gallery-order-item][data-item-id="' + payload.item.id + '"]');

    if (featuredBadge) {
      featuredBadge.hidden = !payload.item.featured;
    }

    if (previewButton) {
      previewButton.dataset.galleryLightboxAlt = payload.item.caption ? payload.item.title + ' - ' + payload.item.caption : payload.item.title;
    }

    if (orderItem) {
      const orderTitle = orderItem.querySelector('[data-gallery-order-title]');
      if (orderTitle) {
        orderTitle.textContent = payload.item.title;
      }
    }
  }

  function submitAutosave(form) {
    if (!window.fetch || form.dataset.isSubmitting === 'true') {
      form.dataset.pendingSave = 'true';
      return;
    }

    form.dataset.isSubmitting = 'true';
    form.dataset.pendingSave = 'false';
    setAutosaveStatus(form, 'Saving...', false);

    fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    }).then(function (response) {
      return response.json().catch(function () {
        return { ok: false, error: 'Unable to save this gallery image right now.' };
      }).then(function (payload) {
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || 'Unable to save this gallery image right now.');
        }

        return payload;
      });
    }).then(function (payload) {
      applyAutosavePayload(form, payload);
      setAutosaveStatus(form, payload.message || 'Saved', false);
    }).catch(function (error) {
      setAutosaveStatus(form, error.message || 'Unable to save this gallery image right now.', true);
    }).finally(function () {
      form.dataset.isSubmitting = 'false';
      if (form.dataset.pendingSave === 'true') {
        submitAutosave(form);
      }
    });
  }

  document.querySelectorAll('[data-gallery-autosave-form]').forEach(function (form) {
    let debounceTimer = null;

    form.addEventListener('input', function (event) {
      if (!(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement)) {
        return;
      }

      if (event.target.type === 'checkbox') {
        return;
      }

      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(function () {
        submitAutosave(form);
      }, 520);
    });

    form.addEventListener('focusout', function (event) {
      if (!(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement)) {
        return;
      }

      if (event.target.type === 'checkbox') {
        return;
      }

      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(function () {
        submitAutosave(form);
      }, 80);
    });

    form.addEventListener('change', function (event) {
      if (!(event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement)) {
        return;
      }

      if (!(event.target.type === 'checkbox' || event.target.tagName === 'SELECT')) {
        return;
      }

      window.clearTimeout(debounceTimer);
      submitAutosave(form);
    });
  });

  function openLightbox(source) {
    if (!lightbox || !lightboxImage || !source) {
      return;
    }

    lightboxImage.src = source.dataset.galleryLightboxSrc || '';
    lightboxImage.alt = source.dataset.galleryLightboxAlt || '';

    if (typeof lightbox.showModal === 'function') {
      lightbox.showModal();
      syncPageScrollLock();
      return;
    }

    lightbox.setAttribute('open', 'open');
    syncPageScrollLock();
  }

  function closeLightbox() {
    if (!lightbox) {
      return;
    }

    if (lightbox.open && typeof lightbox.close === 'function') {
      lightbox.close();
    } else {
      lightbox.removeAttribute('open');
    }

    syncPageScrollLock();
  }

  document.querySelectorAll('[data-gallery-lightbox-open]').forEach(function (button) {
    button.addEventListener('click', function () {
      openLightbox(button);
    });
  });

  if (lightbox) {
    const closeButton = lightbox.querySelector('[data-gallery-lightbox-close]');
    if (closeButton) {
      closeButton.addEventListener('click', closeLightbox);
    }

    lightbox.addEventListener('click', function (event) {
      if (event.target === lightbox) {
        closeLightbox();
      }
    });

    lightbox.addEventListener('cancel', function (event) {
      event.preventDefault();
      closeLightbox();
    });

    lightbox.addEventListener('close', syncPageScrollLock);
  }

  syncPageScrollLock();
})();
