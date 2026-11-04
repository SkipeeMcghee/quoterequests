// Extracted from app/templates/admin/recurring_work_detail.html — keep behaviour identical.
    (function () {
      var forms = document.querySelectorAll('[data-recurring-edit-form]');
      var editForm = document.querySelector('[data-recurring-edit-form]');
      var autosaveForm = document.querySelector('[data-recurring-edit-form]');
      var autosaveStatus = autosaveForm ? autosaveForm.closest('.summary-card').querySelector('[data-recurring-autosave-status]') : null;
      var summaryCustomerLink = document.querySelector('[data-recurring-summary-customer-link]');

      function setAutosaveStatus(message, isError, state) {
        if (!autosaveStatus) {
          return;
        }

        if (autosaveForm && autosaveForm._recurringAutosaveTimer) {
          window.clearTimeout(autosaveForm._recurringAutosaveTimer);
          autosaveForm._recurringAutosaveTimer = null;
        }

        autosaveStatus.textContent = message || '';
        autosaveStatus.dataset.state = message ? (isError ? 'error' : state || 'saved') : '';

        if (message && !isError && state !== 'saving' && autosaveForm) {
          autosaveForm._recurringAutosaveTimer = window.setTimeout(function () {
            autosaveStatus.textContent = '';
            autosaveStatus.dataset.state = '';
          }, 1800);
        }
      }

      function applyRecurringAutosavePayload(payload) {
        if (!payload || !payload.work) {
          return;
        }

        hasAutosaveChanges = true;
        var work = payload.work;
        var summaryTitle = document.querySelector('[data-recurring-summary-title]');
        var summaryStatus = document.querySelector('[data-recurring-summary-status]');
        var summaryGenerated = document.querySelector('[data-recurring-summary-generated]');
        var summaryFrequency = document.querySelector('[data-recurring-summary-frequency]');
        var summaryCadence = document.querySelector('[data-recurring-summary-cadence]');
        var summaryTime = document.querySelector('[data-recurring-summary-time]');
        var summaryStarts = document.querySelector('[data-recurring-summary-starts]');
        var summaryCustomerLink = document.querySelector('[data-recurring-summary-customer-link]');
        var summaryManaged = document.querySelector('[data-recurring-summary-managed]');
        var summaryProtected = document.querySelector('[data-recurring-summary-protected]');
        var summaryBilling = document.querySelector('[data-recurring-summary-billing]');

        if (summaryTitle) {
          summaryTitle.textContent = work.display_title || work.title || 'Service not set';
        }
        if (summaryStatus) {
          summaryStatus.textContent = work.status_label;
        }
        if (summaryGenerated) {
          summaryGenerated.textContent = work.upcoming_generated_count + ' upcoming of ' + work.generated_count + ' total child event' + (work.generated_count === 1 ? '' : 's');
        }
        if (summaryFrequency) {
          summaryFrequency.textContent = work.frequency_label;
        }
        if (summaryCadence) {
          summaryCadence.textContent = work.cadence_summary;
        }
        if (summaryTime) {
          summaryTime.textContent = work.time_summary;
        }
        if (summaryStarts) {
          summaryStarts.textContent = work.starts_label + ' ' + work.starts_on_label;
        }
        if (summaryCustomerLink) {
          if (work.customer_id) {
            summaryCustomerLink.innerHTML = '<a href="/admin/customers/' + work.customer_id + '">' + (work.customer_name || 'Customer') + '</a>';
          } else {
            summaryCustomerLink.textContent = 'No linked customer';
          }
        }
        if (summaryManaged) {
          summaryManaged.textContent = work.future_managed_event_count + ' future event' + (work.future_managed_event_count === 1 ? '' : 's');
        }
        if (summaryProtected) {
          summaryProtected.textContent = work.protected_event_count + ' inside current synced window';
        }
        if (summaryBilling) {
          summaryBilling.textContent = work.billing_summary;
        }
      }

      function submitRecurringAutosave(form) {
        if (!form || !window.fetch) {
          return Promise.resolve();
        }

        if (form.dataset.isSubmitting === 'true') {
          form.dataset.pendingSave = 'true';
          return form._recurringAutosavePromise || Promise.resolve();
        }

        form.dataset.isSubmitting = 'true';
        form.dataset.pendingSave = 'false';
        setAutosaveStatus('Saving recurring work...', false, 'saving');

        form._recurringAutosavePromise = fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          }
        }).then(function (response) {
          return response.json().catch(function () {
            return { ok: false, error: 'Unable to save the recurring plan right now.' };
          }).then(function (payload) {
            if (!response.ok || !payload.ok) {
              throw new Error(payload.error || 'Unable to save the recurring plan right now.');
            }
            return payload;
          });
        }).then(function (payload) {
          applyRecurringAutosavePayload(payload);
          isRecurringFormDirty = false;
          setAutosaveStatus(payload.message || 'Saved', false);
          return payload;
        }).catch(function (error) {
          setAutosaveStatus(error.message || 'Unable to save the recurring plan right now.', true);
          throw error;
        }).finally(function () {
          form.dataset.isSubmitting = 'false';
          if (form.dataset.pendingSave === 'true') {
            submitRecurringAutosave(form);
          }
          form._recurringAutosavePromise = null;
        });

        return form._recurringAutosavePromise;
      }

      var generatedDialog = document.getElementById('recurring-generated-dialog');
      var syncAnchor = 'generated-appointments';
      var hasAutosaveChanges = false;
      var isRecurringFormDirty = false;

      var updatePopupState = function () {
        document.body.classList.toggle('gallery-popup-open', generatedDialog && generatedDialog.hasAttribute('open'));
      };

      var openGeneratedDialog = function () {
        if (!generatedDialog) {
          return;
        }

        if (typeof generatedDialog.showModal === 'function') {
          generatedDialog.showModal();
        } else {
          generatedDialog.setAttribute('open', 'open');
        }
        updatePopupState();
      };

      var closeGeneratedDialog = function () {
        if (!generatedDialog) {
          return;
        }

        if (generatedDialog.open && typeof generatedDialog.close === 'function') {
          generatedDialog.close();
        } else {
          generatedDialog.removeAttribute('open');
        }
        if (window.location.hash === '#' + syncAnchor) {
          history.replaceState(null, '', window.location.pathname + window.location.search);
        }
        updatePopupState();
      };

      forms.forEach(function (form) {
        var presetInput = form.querySelector('[data-recurring-preset-input]');
        var unitInput = form.querySelector('[data-recurring-unit-input]');
        var startsOnInput = form.querySelector('input[name$="starts_on"]');
        if (!presetInput || !unitInput) {
          return;
        }

        var getWeekdayDefault = function () {
          if (startsOnInput && startsOnInput.value) {
            var parsed = new Date(startsOnInput.value + 'T00:00:00');
            if (!Number.isNaN(parsed.getTime())) {
              return (parsed.getDay() + 6) % 7;
            }
          }
          return (new Date().getDay() + 6) % 7;
        };

        var getMonthDayDefault = function () {
          if (startsOnInput && startsOnInput.value) {
            var parsed = new Date(startsOnInput.value + 'T00:00:00');
            if (!Number.isNaN(parsed.getTime())) {
              return parsed.getDate();
            }
          }
          return new Date().getDate();
        };

        var setWeekdaySelection = function (selectedValues) {
          var selectedLookup = new Set(selectedValues.map(String));
          form.querySelectorAll('input[name$="weekdays"]').forEach(function (input) {
            input.checked = selectedLookup.has(input.value);
          });
        };

        var updateVisibility = function () {
          var unit = unitInput.value;
          form.querySelectorAll('[data-recurring-unit-target]').forEach(function (field) {
            var shouldShow = field.getAttribute('data-recurring-unit-target') === unit;
            field.classList.toggle('is-hidden', !shouldShow);
            field.querySelectorAll('select, input').forEach(function (input) {
              input.disabled = !shouldShow;
            });
          });

        };

        var applyPreset = function () {
          var intervalInput = form.querySelector('input[name$="recurrence_interval"]');
          var monthDayInputs = form.querySelectorAll('input[name$="month_days"]');
          var defaultWeekday = String(getWeekdayDefault());
          var defaultMonthDay = String(getMonthDayDefault());

          var setMonthDaySelection = function (selectedValues) {
            var selectedLookup = new Set(selectedValues.map(String));
            monthDayInputs.forEach(function (input) {
              input.checked = selectedLookup.has(input.value);
            });
          };

          if (!intervalInput || !monthDayInputs.length) {
            updateVisibility();
            return;
          }

          if (presetInput.value === 'weekly') {
            unitInput.value = 'week';
            intervalInput.value = '1';
            setWeekdaySelection([defaultWeekday]);
          } else if (presetInput.value === 'biweekly') {
            unitInput.value = 'week';
            intervalInput.value = '2';
            setWeekdaySelection([defaultWeekday]);
          } else if (presetInput.value === 'monthly') {
            unitInput.value = 'month';
            intervalInput.value = '1';
            setMonthDaySelection([defaultMonthDay]);
          } else if (presetInput.value === 'semi_monthly') {
            unitInput.value = 'month';
            intervalInput.value = '1';
            setMonthDaySelection([defaultMonthDay, defaultMonthDay === '15' ? '1' : '15']);
          } else if (presetInput.value === 'bimonthly') {
            unitInput.value = 'month';
            intervalInput.value = '2';
            setMonthDaySelection([defaultMonthDay]);
          }

          updateVisibility();
        };

        presetInput.addEventListener('change', applyPreset);
        unitInput.addEventListener('change', updateVisibility);
        updateVisibility();
        applyPreset();
      });

      if (autosaveForm) {
        var autosaveDebounceTimer = null;
        var serviceTitleInput = autosaveForm.querySelector('input[name$="title"]');
        var serviceCheckboxes = Array.from(autosaveForm.querySelectorAll('input[type="checkbox"][name$="service_ids"]'));
        var formSummaryTitle = document.querySelector('[data-recurring-summary-title]');

        function getServiceLabel(checkbox) {
          var label = checkbox.closest('label');
          if (label) {
            return label.textContent.trim();
          }
          return checkbox.value;
        }

        function getSelectedServiceNames() {
          return serviceCheckboxes.filter(function (checkbox) {
            return checkbox.checked;
          }).map(function (checkbox) {
            return getServiceLabel(checkbox);
          });
        }

        function updateServiceTitleFromSelection() {
          var selectedNames = getSelectedServiceNames();
          if (selectedNames.length === 0) {
            return;
          }
          var title = selectedNames.join(', ');
          if (serviceTitleInput) {
            serviceTitleInput.value = title;
          }
          if (formSummaryTitle) {
            formSummaryTitle.textContent = title;
          }
        }

        serviceCheckboxes.forEach(function (checkbox) {
          checkbox.addEventListener('click', function (event) {
            var checkedBoxes = serviceCheckboxes.filter(function (box) {
              return box.checked;
            });
            if (checkbox.checked && checkedBoxes.length === 1) {
              event.preventDefault();
              setAutosaveStatus('Choose at least one service.', true, 'error');
            }
          });

          checkbox.addEventListener('change', function () {
            var selectedNames = getSelectedServiceNames();
            if (selectedNames.length === 0) {
              checkbox.checked = true;
              setAutosaveStatus('Choose at least one service.', true, 'error');
              return;
            }
            updateServiceTitleFromSelection();
          });
        });

        autosaveForm.addEventListener('submit', function (event) {
          event.preventDefault();
          window.clearTimeout(autosaveDebounceTimer);
          submitRecurringAutosave(autosaveForm);
        });

        autosaveForm.addEventListener('input', function (event) {
          if (!(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement)) {
            return;
          }

          if (event.target.name && event.target.name.endsWith('customer_lookup')) {
            return;
          }
          if (event.target.type === 'checkbox' || event.target.type === 'hidden') {
            return;
          }

          window.clearTimeout(autosaveDebounceTimer);
          autosaveDebounceTimer = window.setTimeout(function () {
            submitRecurringAutosave(autosaveForm);
          }, 520);
        });

        autosaveForm.addEventListener('focusout', function (event) {
          if (!(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement)) {
            return;
          }

          if (event.target.name && event.target.name.endsWith('customer_lookup')) {
            return;
          }
          if (event.target.type === 'checkbox' || event.target.type === 'hidden') {
            return;
          }

          window.clearTimeout(autosaveDebounceTimer);
          autosaveDebounceTimer = window.setTimeout(function () {
            submitRecurringAutosave(autosaveForm);
          }, 80);
        });

        autosaveForm.addEventListener('change', function (event) {
          if (!(event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement)) {
            return;
          }

          if (event.target.type === 'hidden' && event.target.name && event.target.name.endsWith('customer_id')) {
            updateCustomerSummaryLink(event.target.value, autosaveForm.querySelector('input[name$="customer_lookup"]').value);
            window.clearTimeout(autosaveDebounceTimer);
            submitRecurringAutosave(autosaveForm);
            return;
          }

          if (!(event.target.type === 'checkbox' || event.target.tagName === 'SELECT')) {
            return;
          }

          window.clearTimeout(autosaveDebounceTimer);
          submitRecurringAutosave(autosaveForm);
        });

        function updateCustomerSummaryLink(customerId, customerName) {
          if (!summaryCustomerLink) {
            return;
          }

          if (customerId) {
            summaryCustomerLink.innerHTML = '<a href="/admin/customers/' + customerId + '">' + (customerName || 'Customer') + '</a>';
          } else {
            summaryCustomerLink.textContent = 'No linked customer';
          }
        }

        window.addEventListener('beforeunload', function (event) {
          if (autosaveForm.dataset.isSubmitting === 'true' || autosaveForm.dataset.pendingSave === 'true' || isRecurringFormDirty) {
            event.preventDefault();
            event.returnValue = '';
          }
        });
      }

      var generateRecurringForm = document.querySelector('[data-recurring-generated-form]');
      if (generateRecurringForm) {
        var daysAheadSelect = generateRecurringForm.querySelector('select[name$="days_ahead"]');
        if (daysAheadSelect) {
          daysAheadSelect.addEventListener('change', function () {
            generateRecurringForm.submit();
          });
        }
      }

      if (autosaveForm) {
        autosaveForm.addEventListener('input', function (event) {
          if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) {
            isRecurringFormDirty = true;
          }
        });
      }

      document.querySelectorAll('[data-recurring-generated-open]').forEach(function (button) {
        button.addEventListener('click', function () {
          var openUrl = window.location.pathname + window.location.search + '#generated-appointments';
          var shouldRefresh = isRecurringFormDirty || hasAutosaveChanges || (autosaveForm && (autosaveForm.dataset.isSubmitting === 'true' || autosaveForm.dataset.pendingSave === 'true'));
          if (shouldRefresh) {
            submitRecurringAutosave(autosaveForm).finally(function () {
              window.location.href = openUrl;
              window.location.reload();
            });
            return;
          }

          openGeneratedDialog();
        });
      });

      if (generatedDialog) {
        generatedDialog.querySelectorAll('[data-recurring-generated-close]').forEach(function (button) {
          button.addEventListener('click', function () {
            closeGeneratedDialog();
          });
        });

        generatedDialog.addEventListener('cancel', function (event) {
          event.preventDefault();
          closeGeneratedDialog();
        });

        generatedDialog.addEventListener('close', function () {
          updatePopupState();
        });

        if (window.location.hash === '#' + syncAnchor) {
          openGeneratedDialog();
        }
      }
    }());
  
