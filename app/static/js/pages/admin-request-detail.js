// Extracted from app/templates/admin/request_detail.html — keep behaviour identical.
(function () {
  const requestDetailScrollKey = 'admin-request-detail-scroll';
  const lastContactedForm = document.getElementById('last-contacted-form');
  const lastContactedInput = document.getElementById('last-contacted-on');
  const lastContactedClearButton = document.getElementById('last-contacted-clear');
  const requestDetailRefreshRegionIds = [
    'request-detail-customer-panel',
    'request-detail-customer-field',
    'request-detail-scheduling-region'
  ];
  const scheduleDialogId = 'request-scheduling-dialog';

  function getScheduleDialog() {
    return document.getElementById(scheduleDialogId);
  }

  function openScheduleDialog() {
    const dialog = getScheduleDialog();
    if (!dialog) {
      return;
    }

    if (typeof dialog.showModal === 'function') {
      if (!dialog.open) {
        dialog.showModal();
      }
      return;
    }

    dialog.setAttribute('open', 'open');
  }

  function closeScheduleDialog(options) {
    const dialog = getScheduleDialog();
    const closeOptions = options || {};
    if (dialog) {
      if (typeof dialog.close === 'function' && dialog.open) {
        dialog.close();
      } else {
        dialog.removeAttribute('open');
      }
    }

    if (!closeOptions.preserveHash && window.location.hash === '#scheduling' && window.history && typeof window.history.replaceState === 'function') {
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
  }

  function initializeScheduleDialog(root) {
    root.querySelectorAll('#' + scheduleDialogId).forEach(function (dialog) {
      if (dialog.dataset.requestScheduleBound === 'true') {
        return;
      }

      dialog.dataset.requestScheduleBound = 'true';
      dialog.addEventListener('click', function (event) {
        if (event.target === dialog) {
          closeScheduleDialog();
        }
      });

      dialog.addEventListener('close', function () {
        if (window.location.hash === '#scheduling' && window.history && typeof window.history.replaceState === 'function') {
          window.history.replaceState(null, '', window.location.pathname + window.location.search);
        }
      });
    });
  }

  function initializeScheduleDialogTriggers(root) {
    const bindingHost = root.documentElement || root;
    if (!bindingHost || !bindingHost.dataset) {
      return;
    }

    if (bindingHost.dataset.requestScheduleTriggerBound === 'true') {
      return;
    }

    bindingHost.dataset.requestScheduleTriggerBound = 'true';
    root.addEventListener('click', function (event) {
      if (!(event.target instanceof Element)) {
        return;
      }

      const openTrigger = event.target.closest('[data-request-scheduling-open]');
      if (openTrigger) {
        event.preventDefault();
        openScheduleDialog();
        return;
      }

      const closeTrigger = event.target.closest('[data-request-scheduling-close]');
      if (closeTrigger) {
        event.preventDefault();
        closeScheduleDialog();
      }
    });
  }

  function openScheduleDialogFromHash() {
    if (window.location.hash === '#scheduling') {
      openScheduleDialog();
    }
  }

  function initializeScrollAnchorForms(root) {
    root.querySelectorAll('form[data-scroll-anchor]').forEach(function (form) {
      if (form.dataset.scrollRestoreBound === 'true') {
        return;
      }

      form.dataset.scrollRestoreBound = 'true';
      form.addEventListener('submit', function () {
        const anchorId = form.dataset.scrollAnchor;
        const target = anchorId ? document.getElementById(anchorId) : null;
        if (!target) {
          return;
        }

        try {
          sessionStorage.setItem(requestDetailScrollKey, JSON.stringify({
            path: window.location.pathname,
            anchorId,
            topOffset: target.getBoundingClientRect().top,
          }));
        } catch (error) {
          // Ignore storage issues and fall back to normal anchor behavior.
        }
      });
    });
  }

  function replaceFlashStack(nextDocument) {
    const currentFlashStack = document.querySelector('.flash-stack');
    const nextFlashStack = nextDocument.querySelector('.flash-stack');
    const pageShell = document.querySelector('.page-shell');
    const requestDetailPage = document.querySelector('.dashboard-shell');

    if (!pageShell || !requestDetailPage) {
      return;
    }

    if (currentFlashStack && nextFlashStack) {
      currentFlashStack.replaceWith(nextFlashStack.cloneNode(true));
      return;
    }

    if (currentFlashStack && !nextFlashStack) {
      currentFlashStack.remove();
      return;
    }

    if (!currentFlashStack && nextFlashStack) {
      pageShell.insertBefore(nextFlashStack.cloneNode(true), requestDetailPage);
    }
  }

  function replaceRequestDetailRefreshRegions(nextDocument) {
    const scheduleDialog = getScheduleDialog();
    const shouldReopenScheduleDialog = !!(scheduleDialog && scheduleDialog.open);

    requestDetailRefreshRegionIds.forEach(function (regionId) {
      const currentRegion = document.getElementById(regionId);
      const nextRegion = nextDocument.getElementById(regionId);

      if (!currentRegion || !nextRegion) {
        return;
      }

      currentRegion.replaceWith(nextRegion.cloneNode(true));
    });

    return shouldReopenScheduleDialog;
  }

  function initializeRequestDetailAutosubmitForms(root) {
    root.querySelectorAll('form[data-auto-submit-request-detail="true"]').forEach(function (form) {
      if (form.dataset.autoSubmitRequestDetailBound === 'true') {
        return;
      }

      form.dataset.autoSubmitRequestDetailBound = 'true';
      form.addEventListener('change', function (event) {
        const target = event.target;
        if (!target || !target.matches('input[type="checkbox"], input[type="radio"], select')) {
          return;
        }

        if (form.dataset.isSubmitting === 'true') {
          return;
        }

        if (typeof form.requestSubmit === 'function') {
          form.requestSubmit();
          return;
        }

        HTMLFormElement.prototype.submit.call(form);
      });
    });
  }

  function initializeRequestDetailRefreshForms(root) {
    root.querySelectorAll('form[data-request-detail-refresh="true"]').forEach(function (form) {
      if (form.dataset.requestDetailRefreshBound === 'true') {
        return;
      }

      form.dataset.requestDetailRefreshBound = 'true';
      form.addEventListener('submit', function (event) {
        if (form.dataset.forceSyncSubmit === 'true') {
          form.dataset.forceSyncSubmit = 'false';
          return;
        }

        if (!window.fetch || !window.DOMParser) {
          return;
        }

        event.preventDefault();
        if (form.dataset.isSubmitting === 'true') {
          return;
        }

        const preservedScrollY = window.scrollY;
        form.dataset.isSubmitting = 'true';

        fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          }
        }).then(function (response) {
          return response.text().then(function (html) {
            return {
              html: html,
              url: response.url || window.location.href
            };
          });
        }).then(function (result) {
          const nextDocument = new DOMParser().parseFromString(result.html, 'text/html');
          if (!nextDocument.getElementById('request-detail-customer-panel')) {
            window.location.assign(result.url);
            return;
          }

          replaceFlashStack(nextDocument);
          const shouldReopenScheduleDialog = replaceRequestDetailRefreshRegions(nextDocument);
          initializeScrollAnchorForms(document);
          initializeRequestDetailRefreshForms(document);
          initializeRequestDetailAutosubmitForms(document);
          initializeScheduleDialog(document);

          if (window.initializeCustomerComboboxes) {
            window.initializeCustomerComboboxes(document);
          }

          if (shouldReopenScheduleDialog) {
            requestAnimationFrame(function () {
              openScheduleDialog();
            });
          }

          window.scrollTo(0, preservedScrollY);
          requestAnimationFrame(function () {
            window.scrollTo(0, preservedScrollY);
          });
        }).catch(function () {
          form.dataset.forceSyncSubmit = 'true';
          HTMLFormElement.prototype.submit.call(form);
        }).finally(function () {
          form.dataset.isSubmitting = 'false';
        });
      });
    });
  }

  initializeScrollAnchorForms(document);
  initializeRequestDetailRefreshForms(document);
  initializeRequestDetailAutosubmitForms(document);
  initializeScheduleDialog(document);
  initializeScheduleDialogTriggers(document);
  openScheduleDialogFromHash();

  window.addEventListener('hashchange', function () {
    if (window.location.hash === '#scheduling') {
      openScheduleDialog();
      return;
    }

    const scheduleDialog = getScheduleDialog();
    if (scheduleDialog && scheduleDialog.open) {
      closeScheduleDialog({preserveHash: true});
    }
  });

  try {
    const savedScrollState = sessionStorage.getItem(requestDetailScrollKey);
    if (savedScrollState) {
      sessionStorage.removeItem(requestDetailScrollKey);
      const scrollState = JSON.parse(savedScrollState);
      if (scrollState && scrollState.path === window.location.pathname && scrollState.anchorId) {
        const target = document.getElementById(scrollState.anchorId);
        if (target) {
          requestAnimationFrame(function () {
            requestAnimationFrame(function () {
              const desiredTop = window.scrollY + target.getBoundingClientRect().top - (scrollState.topOffset || 0);
              window.scrollTo(0, Math.max(0, desiredTop));
            });
          });
        }
      }
    }
  } catch (error) {
    sessionStorage.removeItem(requestDetailScrollKey);
  }

  function updateLastContactedClearVisibility() {
    if (!lastContactedInput || !lastContactedClearButton) {
      return;
    }

    lastContactedClearButton.hidden = !lastContactedInput.value;
  }

  if (lastContactedForm && lastContactedInput) {
    updateLastContactedClearVisibility();

    lastContactedInput.addEventListener('input', updateLastContactedClearVisibility);
    lastContactedInput.addEventListener('change', function () {
      updateLastContactedClearVisibility();
      lastContactedForm.submit();
    });

    if (lastContactedClearButton) {
      lastContactedClearButton.addEventListener('click', function () {
        if (!lastContactedInput.value) {
          updateLastContactedClearVisibility();
          return;
        }

        lastContactedInput.value = '';
        updateLastContactedClearVisibility();

        if (typeof lastContactedForm.requestSubmit === 'function') {
          lastContactedForm.requestSubmit();
          return;
        }

        lastContactedForm.submit();
      });
    }
  }

  document.querySelectorAll('[data-auto-submit-on-change]').forEach(function (input) {
    input.addEventListener('change', function () {
      const form = input.form;
      if (!form || form.dataset.isSubmitting === 'true') {
        return;
      }

      const feedback = form.querySelector('.request-quote-item__status-feedback');
      const previousValue = input.dataset.previousValue || input.defaultValue || input.value;
      form.dataset.isSubmitting = 'true';
      if (feedback) {
        feedback.textContent = 'Saving...';
      }
      input.disabled = true;

      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      }).then(function (response) {
        return response.json().catch(function () {
          return {ok: false, error: 'Unable to save quote status right now.'};
        }).then(function (payload) {
          if (!response.ok || !payload.ok) {
            throw new Error(payload.error || 'Unable to save quote status right now.');
          }

          return payload;
        });
      }).then(function (payload) {
        input.dataset.previousValue = payload.decision || input.value;
        if (feedback) {
          feedback.textContent = 'Saved';
          window.setTimeout(function () {
            if (feedback.textContent === 'Saved') {
              feedback.textContent = '';
            }
          }, 1600);
        }
      }).catch(function (error) {
        input.value = previousValue;
        if (feedback) {
          feedback.textContent = error.message || 'Unable to save quote status right now.';
        }
      }).finally(function () {
        input.disabled = false;
        form.dataset.isSubmitting = 'false';
      });
    });
  });

  document.querySelectorAll('[data-internal-note]').forEach(function (container) {
    const toggle = container.querySelector('[data-internal-note-toggle]');
    const editor = container.querySelector('#internal-note-editor');
    if (!toggle || !editor) {
      return;
    }

    toggle.addEventListener('click', function () {
      const willExpand = editor.hidden;
      editor.hidden = !willExpand;
      toggle.setAttribute('aria-expanded', willExpand ? 'true' : 'false');
      toggle.textContent = willExpand ? 'Collapse internal note' : 'Expand internal note';
      if (willExpand) {
        const noteField = editor.querySelector('textarea[name="note_text"]');
        if (noteField) {
          noteField.focus();
        }
      }
    });
  });

  function initializeQuoteDraftAutosave() {
    const quoteForm = document.getElementById('request-quote-form');
    const feedback = document.getElementById('request-quote-draft-feedback');
    const amountInput = quoteForm ? quoteForm.querySelector('input[name="request-quote-amount"]') : null;
    const billingSelect = quoteForm ? quoteForm.querySelector('select[name="request-quote-billing_frequency"]') : null;
    const descriptionInput = quoteForm ? quoteForm.querySelector('input[name="request-quote-description"]') : null;
    const draftAction = quoteForm ? quoteForm.dataset.draftAction : '';

    if (!quoteForm || !feedback || !amountInput || !billingSelect || !descriptionInput || !draftAction) {
      return;
    }

    let debounceTimer = null;
    let inFlight = false;
    let formSubmitting = false;
    let lastFingerprint = [
      (amountInput.value || '').trim(),
      billingSelect.value || '',
      (descriptionInput.value || '').trim(),
    ].join('|');

    quoteForm.addEventListener('submit', function () {
      formSubmitting = true;
    });

    function setFeedback(state, message) {
      if (state === 'saving') {
        feedback.textContent = 'saving';
        return;
      }

      if (state === 'saved') {
        feedback.textContent = 'saved';
        window.setTimeout(function () {
          if (feedback.textContent === 'saved') {
            feedback.textContent = '';
          }
        }, 1800);
        return;
      }

      if (state === 'error') {
        feedback.textContent = message || 'Unable to save draft right now.';
        return;
      }

      feedback.textContent = '';
    }

    function saveDraftNow() {
      if (formSubmitting || inFlight) {
        return;
      }

      const nextFingerprint = [
        (amountInput.value || '').trim(),
        billingSelect.value || '',
        (descriptionInput.value || '').trim(),
      ].join('|');

      if (nextFingerprint === lastFingerprint) {
        return;
      }

      inFlight = true;
      setFeedback('saving');

      fetch(draftAction, {
        method: 'POST',
        body: new FormData(quoteForm),
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      }).then(function (response) {
        return response.json().catch(function () {
          return {ok: false, error: 'Unable to save draft right now.'};
        }).then(function (payload) {
          if (!response.ok || !payload.ok) {
            throw new Error(payload.error || 'Unable to save draft right now.');
          }
          return payload;
        });
      }).then(function () {
        lastFingerprint = nextFingerprint;
        setFeedback('saved');
      }).catch(function (error) {
        setFeedback('error', error.message);
      }).finally(function () {
        inFlight = false;
      });
    }

    [amountInput, billingSelect, descriptionInput].forEach(function (input) {
      input.addEventListener(input.tagName === 'SELECT' ? 'change' : 'input', function () {
        if (debounceTimer) {
          window.clearTimeout(debounceTimer);
        }
        debounceTimer = window.setTimeout(saveDraftNow, 700);
      });
    });
  }

  initializeQuoteDraftAutosave();

  function initializeInternalNoteAutosave() {
    const noteForm = document.getElementById('internal-note-editor');
    const noteInput = noteForm ? noteForm.querySelector('textarea[name="note_text"]') : null;
    const noteFeedback = document.getElementById('request-note-feedback');

    if (!noteForm || !noteInput || !noteFeedback) {
      return;
    }

    let debounceTimer = null;
    let inFlight = false;
    let lastFingerprint = (noteInput.value || '').trim();

    function setNoteFeedback(state, message) {
      if (state === 'saving') {
        noteFeedback.textContent = 'saving';
        return;
      }

      if (state === 'saved') {
        noteFeedback.textContent = 'saved';
        window.setTimeout(function () {
          if (noteFeedback.textContent === 'saved') {
            noteFeedback.textContent = '';
          }
        }, 1800);
        return;
      }

      if (state === 'error') {
        noteFeedback.textContent = message || 'Unable to save right now.';
        return;
      }

      noteFeedback.textContent = '';
    }

    function saveNow() {
      if (inFlight) {
        return;
      }

      const nextFingerprint = (noteInput.value || '').trim();
      if (!nextFingerprint || nextFingerprint === lastFingerprint) {
        return;
      }

      inFlight = true;
      setNoteFeedback('saving');

      fetch(noteForm.action, {
        method: 'POST',
        body: new FormData(noteForm),
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      }).then(function (response) {
        return response.json().catch(function () {
          return {ok: false, error: 'Unable to save right now.'};
        }).then(function (payload) {
          if (!response.ok || !payload.ok) {
            throw new Error(payload.error || 'Unable to save right now.');
          }
          return payload;
        });
      }).then(function () {
        lastFingerprint = nextFingerprint;
        setNoteFeedback('saved');
      }).catch(function (error) {
        setNoteFeedback('error', error.message);
      }).finally(function () {
        inFlight = false;
      });
    }

    noteForm.addEventListener('submit', function (event) {
      event.preventDefault();
      saveNow();
    });

    noteInput.addEventListener('input', function () {
      if (debounceTimer) {
        window.clearTimeout(debounceTimer);
      }
      debounceTimer = window.setTimeout(saveNow, 700);
    });
  }

  initializeInternalNoteAutosave();

  document.querySelectorAll('[data-photo-gallery]').forEach(function (gallery) {
    const stageImage = gallery.querySelector('[data-gallery-stage]');
    const stageCount = gallery.querySelector('[data-gallery-count]');
    const prevButton = gallery.querySelector('[data-gallery-prev]');
    const nextButton = gallery.querySelector('[data-gallery-next]');
    const thumbsContainer = gallery.querySelector('.request-photo-gallery__thumbs');
    const thumbButtons = Array.from(gallery.querySelectorAll('[data-gallery-thumb]'));
    let activeIndex = 0;
    let windowStart = 0;

    if (!stageImage || !thumbButtons.length || !thumbsContainer) {
      return;
    }

    function getVisibleCount() {
      const containerWidth = thumbsContainer.getBoundingClientRect().width;
      const sampleButton = thumbButtons[0];
      const sampleWidth = sampleButton.getBoundingClientRect().width || parseFloat(window.getComputedStyle(sampleButton).width || '0');
      const styles = window.getComputedStyle(thumbsContainer);
      const gap = parseFloat(styles.columnGap || styles.gap || '0');
      const itemSpan = Math.max(sampleWidth + gap, 1);
      const fittedCount = Math.floor((containerWidth + gap) / itemSpan);

      if (!Number.isFinite(fittedCount) || fittedCount < 1) {
        return Math.min(thumbButtons.length, 5);
      }

      return Math.max(1, Math.min(thumbButtons.length, fittedCount));
    }

    function clampWindowStart(nextStart, visibleCount) {
      const maxStart = Math.max(0, thumbButtons.length - visibleCount);
      return Math.max(0, Math.min(nextStart, maxStart));
    }

    function syncWindowToActive(visibleCount) {
      if (activeIndex < windowStart) {
        windowStart = activeIndex;
      } else if (activeIndex >= windowStart + visibleCount) {
        windowStart = activeIndex - visibleCount + 1;
      }

      windowStart = clampWindowStart(windowStart, visibleCount);
    }

    function render(focusThumb) {
      const visibleCount = getVisibleCount();
      const hasMultiplePhotos = thumbButtons.length > 1;

      syncWindowToActive(visibleCount);

      thumbButtons.forEach(function (button, index) {
        const isActive = index === activeIndex;
        const isVisible = index >= windowStart && index < windowStart + visibleCount;

        button.hidden = !isVisible;
        button.classList.toggle('is-active', isActive);
        button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        button.tabIndex = isVisible ? 0 : -1;
      });

      stageImage.src = thumbButtons[activeIndex].dataset.photoSrc;
      stageImage.alt = thumbButtons[activeIndex].dataset.photoAlt;

      if (stageCount) {
        stageCount.textContent = String(activeIndex + 1) + ' of ' + String(thumbButtons.length);
      }

      if (prevButton) {
        prevButton.hidden = !hasMultiplePhotos;
        prevButton.disabled = !hasMultiplePhotos;
      }

      if (nextButton) {
        nextButton.hidden = !hasMultiplePhotos;
        nextButton.disabled = !hasMultiplePhotos;
      }

      if (focusThumb) {
        thumbButtons[activeIndex].focus();
      }
    }

    thumbButtons.forEach(function (button, index) {
      button.addEventListener('click', function () {
        activeIndex = index;
        render(false);
      });
    });

    if (prevButton) {
      prevButton.addEventListener('click', function () {
        if (thumbButtons.length <= 1) {
          return;
        }

        activeIndex = (activeIndex - 1 + thumbButtons.length) % thumbButtons.length;
        render(true);
      });
    }

    if (nextButton) {
      nextButton.addEventListener('click', function () {
        if (thumbButtons.length <= 1) {
          return;
        }

        activeIndex = (activeIndex + 1) % thumbButtons.length;
        render(true);
      });
    }

    window.addEventListener('resize', function () {
      render(false);
    });

    render(false);
  });

})();
