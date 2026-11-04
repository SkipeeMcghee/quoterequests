// Extracted from app/templates/admin/staff_detail.html — keep behaviour identical.

(function () {
  const notesForm = document.querySelector('[data-staff-notes-form]');
  if (!notesForm || !window.fetch) {
    return;
  }

  const notesInput = notesForm.querySelector('[data-staff-notes-input]');
  const statusElement = notesForm.querySelector('[data-staff-notes-status]');
  if (!notesInput || !statusElement) {
    return;
  }

  const saveDelayMs = 700;
  let savedValue = notesInput.value;
  let saveTimer = null;
  let statusTimer = null;
  let isSaving = false;
  let queuedSave = false;

  function setStatus(message, options) {
    const settings = options || {};
    window.clearTimeout(statusTimer);
    statusElement.textContent = message || '';
    statusElement.dataset.state = settings.isError ? 'error' : (settings.isPending ? '' : (message ? 'success' : ''));

    if (message && !settings.isError && !settings.isPending) {
      statusTimer = window.setTimeout(function () {
        if (statusElement.textContent === message) {
          statusElement.textContent = '';
          statusElement.dataset.state = '';
        }
      }, 1800);
    }
  }

  function saveNotes() {
    window.clearTimeout(saveTimer);
    saveTimer = null;

    if (isSaving) {
      queuedSave = true;
      return;
    }

    if (notesInput.value === savedValue) {
      setStatus('', {});
      return;
    }

    const pendingValue = notesInput.value;
    isSaving = true;
    queuedSave = false;
    setStatus('Saving...', { isPending: true });

    fetch(notesForm.action, {
      method: 'POST',
      body: new FormData(notesForm),
      headers: {
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      }
    }).then(function (response) {
      return response.json().catch(function () {
        return { ok: false, error: 'Unable to save staff notes right now.' };
      }).then(function (payload) {
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || 'Unable to save staff notes right now.');
        }
        return payload;
      });
    }).then(function (payload) {
      savedValue = pendingValue;
      setStatus(payload.message || 'Staff notes saved.', {});
    }).catch(function (error) {
      setStatus(error.message || 'Unable to save staff notes right now.', { isError: true });
    }).finally(function () {
      isSaving = false;
      if (queuedSave || notesInput.value !== savedValue) {
        saveNotes();
      }
    });
  }

  notesInput.addEventListener('input', function () {
    if (notesInput.value === savedValue) {
      queuedSave = false;
      window.clearTimeout(saveTimer);
      saveTimer = null;
      setStatus('', {});
      return;
    }

    setStatus('Saving...', { isPending: true });
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(saveNotes, saveDelayMs);
  });

  notesInput.addEventListener('blur', saveNotes);
})();

(function () {
  const scheduledHoursForm = document.querySelector('[data-scheduled-hours-filter]');
  if (!scheduledHoursForm) {
    return;
  }

  const scheduledHoursScrollKey = 'staff-detail-scheduled-hours-scroll';
  const presetInput = scheduledHoursForm.querySelector('[data-scheduled-hours-preset]');
  const startDateInput = scheduledHoursForm.querySelector('[data-scheduled-hours-start]');
  const endDateInput = scheduledHoursForm.querySelector('[data-scheduled-hours-end]');

  function persistScheduledHoursScroll() {
    try {
      sessionStorage.setItem(scheduledHoursScrollKey, JSON.stringify({
        path: window.location.pathname,
        scrollX: window.scrollX,
        scrollY: window.scrollY,
      }));
    } catch (error) {
      sessionStorage.removeItem(scheduledHoursScrollKey);
    }
  }

  try {
    const savedScrollState = sessionStorage.getItem(scheduledHoursScrollKey);
    if (savedScrollState) {
      sessionStorage.removeItem(scheduledHoursScrollKey);
      const scrollState = JSON.parse(savedScrollState);
      if (scrollState && scrollState.path === window.location.pathname) {
        requestAnimationFrame(function () {
          requestAnimationFrame(function () {
            window.scrollTo(scrollState.scrollX || 0, scrollState.scrollY || 0);
          });
        });
      }
    }
  } catch (error) {
    sessionStorage.removeItem(scheduledHoursScrollKey);
  }

  scheduledHoursForm.addEventListener('submit', function () {
    persistScheduledHoursScroll();
  });

  function submitScheduledHoursForm() {
    if (scheduledHoursForm.dataset.isSubmitting === 'true') {
      return;
    }

    scheduledHoursForm.dataset.isSubmitting = 'true';
    if (scheduledHoursForm.requestSubmit) {
      scheduledHoursForm.requestSubmit();
      return;
    }

    persistScheduledHoursScroll();
    HTMLFormElement.prototype.submit.call(scheduledHoursForm);
  }

  if (presetInput) {
    presetInput.addEventListener('change', function () {
      if (!presetInput.value) {
        return;
      }

      submitScheduledHoursForm();
    });
  }

  [startDateInput, endDateInput].forEach(function (input) {
    if (!input) {
      return;
    }

    input.addEventListener('change', function () {
      if (presetInput) {
        presetInput.value = '';
      }

      if (!startDateInput || !endDateInput || !startDateInput.value || !endDateInput.value) {
        return;
      }

      submitScheduledHoursForm();
    });
  });
})();

(function () {
  const board = document.querySelector('[data-availability-board]');
  if (!board || !window.fetch || !window.PointerEvent) {
    return;
  }

  const weekdayNamesNode = document.querySelector('[data-weekday-names]');
  const weekdayNames = weekdayNamesNode ? JSON.parse(weekdayNamesNode.textContent) : [];
  const stateNode = board.querySelector('[data-availability-board-state]');
  const syncForm = board.querySelector('[data-availability-sync-form]');
  const windowsInput = syncForm ? syncForm.querySelector('input[name$="windows_json"]') : null;
  const statusElement = document.querySelector('[data-availability-status]');
  const emptyState = document.querySelector('[data-availability-empty-state]');
  const manualDaysContainer = document.querySelector('[data-availability-manual-days]');
  const clearButton = document.querySelector('[data-availability-clear]');
  const boardMinutes = Number(board.dataset.boardMinutes || '1435');
  const slotMinutes = Number(board.dataset.slotMinutes || '15');
  const compactThresholdMinutes = 60;
  const defaultManualDurationMinutes = 60;
  const hourOptions = Array.from({ length: 24 }, function (_, hourValue) {
    return { value: hourValue, label: formatDisplayTime(hourValue * 60) };
  });
  const minuteOptions = Array.from({ length: 60 / slotMinutes }, function (_, minuteIndex) {
    const minuteValue = minuteIndex * slotMinutes;
    return { value: minuteValue, label: pad(minuteValue) };
  });
  let tempId = 0;
  let committedWindows = normalizeWindows(readBoardState());
  let workingWindows = cloneWindows(committedWindows);
  let interaction = null;
  let isSaving = false;
  let pendingFocusRestore = null;
  let statusTimer = null;

  function readBoardState() {
    if (!stateNode) {
      return [];
    }

    try {
      return JSON.parse(stateNode.textContent || '[]');
    } catch (error) {
      return [];
    }
  }

  function cloneWindows(source) {
    return source.map(function (windowItem) {
      return Object.assign({}, windowItem);
    });
  }

  function compareWindows(left, right) {
    return (
      left.dayIndex - right.dayIndex
      || left.startMinutes - right.startMinutes
      || left.endMinutes - right.endMinutes
      || String(left.key).localeCompare(String(right.key))
    );
  }

  function clampDayIndex(value) {
    if (Number.isNaN(value)) {
      return 0;
    }
    return Math.max(0, Math.min(6, value));
  }

  function normalizeWindows(source) {
    if (!Array.isArray(source)) {
      return [];
    }

    return source.map(function (windowItem) {
      const numericId = windowItem.id === null || windowItem.id === undefined || windowItem.id === ''
        ? null
        : Number(windowItem.id);
      const rawStartMinutes = Number(windowItem.start_minutes);
      const rawEndMinutes = Number(windowItem.end_minutes);
      const startMinutes = Math.max(0, Math.min(boardMinutes - slotMinutes, Number.isNaN(rawStartMinutes) ? 0 : rawStartMinutes));
      const endMinutes = Math.max(startMinutes + slotMinutes, Math.min(boardMinutes, Number.isNaN(rawEndMinutes) ? startMinutes + slotMinutes : rawEndMinutes));
      return {
        id: Number.isNaN(numericId) ? null : numericId,
        key: windowItem.key || (numericId !== null && !Number.isNaN(numericId) ? 'saved-' + numericId : 'temp-' + (++tempId)),
        dayIndex: clampDayIndex(Number(windowItem.day_of_week)),
        startMinutes: startMinutes,
        endMinutes: endMinutes,
        notes: windowItem.notes || '',
      };
    }).sort(compareWindows);
  }

  function pad(value) {
    return String(value).padStart(2, '0');
  }

  function minutesToIso(minutes) {
    const safeMinutes = Math.max(0, Math.min(boardMinutes, minutes));
    const hourValue = Math.floor(safeMinutes / 60);
    const minuteValue = safeMinutes % 60;
    return pad(hourValue) + ':' + pad(minuteValue);
  }

  function formatDisplayTime(minutes) {
    const safeMinutes = Math.max(0, Math.min(boardMinutes, minutes));
    const hourValue = Math.floor(safeMinutes / 60);
    const minuteValue = safeMinutes % 60;
    const suffix = hourValue < 12 ? 'AM' : 'PM';
    const displayHour = hourValue % 12 || 12;
    if (minuteValue) {
      return displayHour + ':' + pad(minuteValue) + ' ' + suffix;
    }
    return displayHour + ' ' + suffix;
  }

  function formatRange(windowItem) {
    return formatDisplayTime(windowItem.startMinutes) + ' – ' + formatDisplayTime(windowItem.endMinutes);
  }

  function serializeWindows(source) {
    return source.slice().sort(compareWindows).map(function (windowItem) {
      return {
        id: windowItem.id,
        day_of_week: windowItem.dayIndex,
        start_time: minutesToIso(windowItem.startMinutes),
        end_time: minutesToIso(windowItem.endMinutes),
        notes: windowItem.notes || '',
      };
    });
  }

  function duplicateDayWindows(sourceDayIndex, targetDayIndex) {
    const nextWindows = cloneWindows(committedWindows).filter(function (windowItem) {
      return windowItem.dayIndex !== targetDayIndex;
    });

    committedWindows.filter(function (windowItem) {
      return windowItem.dayIndex === sourceDayIndex;
    }).forEach(function (windowItem) {
      nextWindows.push({
        id: null,
        key: 'temp-' + (++tempId),
        dayIndex: targetDayIndex,
        startMinutes: windowItem.startMinutes,
        endMinutes: windowItem.endMinutes,
        notes: windowItem.notes || '',
      });
    });

    nextWindows.sort(compareWindows);
    workingWindows = nextWindows;
  }

  function setStatus(message, isError, persist) {
    if (!statusElement) {
      return;
    }

    window.clearTimeout(statusTimer);
    statusElement.textContent = message || '';
    statusElement.dataset.state = isError ? 'error' : (message ? 'success' : '');
    if (message && !isError && !persist) {
      statusTimer = window.setTimeout(function () {
        if (statusElement.textContent === message) {
          statusElement.textContent = '';
          statusElement.dataset.state = '';
        }
      }, 1800);
    }
  }

  function updateAvailabilitySummary(source) {
    const windows = source || workingWindows;
    if (emptyState) {
      emptyState.hidden = windows.length > 0;
    }
    if (clearButton) {
      clearButton.disabled = windows.length === 0 || isSaving;
    }
  }

  function buildBlock(windowItem) {
    const block = document.createElement('div');
    block.className = 'availability-block';
    if (windowItem.endMinutes - windowItem.startMinutes <= compactThresholdMinutes) {
      block.classList.add('availability-block--compact');
    }
    if (interaction && interaction.key === windowItem.key) {
      block.classList.add('availability-block--active');
    }
    block.dataset.windowKey = windowItem.key;
    block.style.left = ((windowItem.startMinutes / boardMinutes) * 100) + '%';
    block.style.width = (((windowItem.endMinutes - windowItem.startMinutes) / boardMinutes) * 100) + '%';
    block.title = windowItem.notes ? formatRange(windowItem) + ' — ' + windowItem.notes : formatRange(windowItem);

    const startHandle = document.createElement('button');
    startHandle.type = 'button';
    startHandle.className = 'availability-block__handle availability-block__handle--start';
    startHandle.dataset.availabilityHandle = 'start';
    startHandle.setAttribute('aria-label', 'Resize availability start');
    block.appendChild(startHandle);

    const label = document.createElement('span');
    label.className = 'availability-block__label';
    label.textContent = formatRange(windowItem);
    block.appendChild(label);

    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'availability-block__delete';
    deleteButton.dataset.availabilityDelete = 'true';
    deleteButton.setAttribute('aria-label', 'Delete availability');
    deleteButton.textContent = 'x';
    block.appendChild(deleteButton);

    const endHandle = document.createElement('button');
    endHandle.type = 'button';
    endHandle.className = 'availability-block__handle availability-block__handle--end';
    endHandle.dataset.availabilityHandle = 'end';
    endHandle.setAttribute('aria-label', 'Resize availability end');
    block.appendChild(endHandle);

    return block;
  }

  function createSelect(options, selectedValue, datasetValues) {
    const select = document.createElement('select');
    select.className = 'select availability-day-row__select';
    Object.keys(datasetValues).forEach(function (key) {
      select.dataset[key] = datasetValues[key];
    });

    // Two selects inside one wrapping label only labels the first one, so each
    // boundary/part pair names itself.
    if (datasetValues.manualPart) {
      const boundaryLabel = datasetValues.manualBoundary === 'start' ? 'Start time' : 'End time';
      const partLabel = datasetValues.manualPart === 'hour' ? 'hour' : 'minutes';
      select.setAttribute('aria-label', boundaryLabel + ' ' + partLabel);
    }

    options.forEach(function (option) {
      const optionElement = document.createElement('option');
      optionElement.value = String(option.value);
      optionElement.textContent = option.label;
      if (String(option.value) === String(selectedValue)) {
        optionElement.selected = true;
      }
      select.appendChild(optionElement);
    });

    return select;
  }

  function buildTimeEditor(labelText, boundary, totalMinutes) {
    const wrapper = document.createElement('label');
    wrapper.className = 'availability-day-row__time';

    const label = document.createElement('span');
    label.textContent = labelText;
    wrapper.appendChild(label);

    const selects = document.createElement('div');
    selects.className = 'availability-day-row__time-selects';
    selects.appendChild(createSelect(hourOptions, Math.floor(totalMinutes / 60), { manualBoundary: boundary, manualPart: 'hour' }));
    selects.appendChild(createSelect(minuteOptions, totalMinutes % 60, { manualBoundary: boundary, manualPart: 'minute' }));
    wrapper.appendChild(selects);

    return wrapper;
  }

  function buildManualRow(windowItem) {
    const row = document.createElement('div');
    row.className = 'availability-day-row';
    row.dataset.manualWindowKey = windowItem.key;
    row.dataset.manualDayIndex = String(windowItem.dayIndex);
    row.dataset.manualStartMinutes = String(windowItem.startMinutes);
    row.dataset.manualEndMinutes = String(windowItem.endMinutes);

    const fields = document.createElement('div');
    fields.className = 'availability-day-row__fields';
    fields.appendChild(buildTimeEditor('Start', 'start', windowItem.startMinutes));
    fields.appendChild(buildTimeEditor('End', 'end', windowItem.endMinutes));
    row.appendChild(fields);

    const actions = document.createElement('div');
    actions.className = 'availability-day-row__actions';

    const range = document.createElement('span');
    range.className = 'subtle-text availability-day-row__summary';
    range.textContent = formatRange(windowItem);
    actions.appendChild(range);

    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'btn btn-secondary btn-small';
    removeButton.dataset.manualRemove = windowItem.key;
    removeButton.textContent = 'Remove';
    actions.appendChild(removeButton);

    row.appendChild(actions);
    return row;
  }

  function createManualFocusSnapshot(details) {
    return {
      kind: 'select',
      windowKey: details.windowKey || null,
      dayIndex: String(details.dayIndex),
      startMinutes: String(details.startMinutes),
      endMinutes: String(details.endMinutes),
      boundary: details.boundary,
      part: details.part,
      windowScrollX: window.scrollX,
      windowScrollY: window.scrollY,
    };
  }

  function createManualButtonSnapshot(dayIndex) {
    return {
      kind: 'button',
      dayIndex: String(dayIndex),
      windowScrollX: window.scrollX,
      windowScrollY: window.scrollY,
    };
  }

  function createScrollSnapshot() {
    return {
      kind: 'scroll',
      windowScrollX: window.scrollX,
      windowScrollY: window.scrollY,
    };
  }

  function captureManualFocus() {
    if (!manualDaysContainer) {
      return null;
    }

    const activeElement = document.activeElement;
    if (!activeElement || !manualDaysContainer.contains(activeElement)) {
      return null;
    }

    const row = activeElement.closest('[data-manual-window-key]');
    if (!row || !activeElement.matches('select[data-manual-boundary][data-manual-part]')) {
      return null;
    }

    return {
      windowKey: row.dataset.manualWindowKey,
      dayIndex: row.dataset.manualDayIndex,
      startMinutes: row.dataset.manualStartMinutes,
      endMinutes: row.dataset.manualEndMinutes,
      boundary: activeElement.dataset.manualBoundary,
      part: activeElement.dataset.manualPart,
      windowScrollX: window.scrollX,
      windowScrollY: window.scrollY,
    };
  }

  function restoreManualFocus(snapshot) {
    if (!snapshot || !manualDaysContainer) {
      return;
    }

    if (snapshot.kind === 'scroll') {
      window.scrollTo(snapshot.windowScrollX, snapshot.windowScrollY);
      return;
    }

    if (snapshot.kind === 'button') {
      const addButton = manualDaysContainer.querySelector('[data-manual-add-day="' + snapshot.dayIndex + '"]');
      window.scrollTo(snapshot.windowScrollX, snapshot.windowScrollY);
      if (addButton) {
        addButton.focus({ preventScroll: true });
      }
      return;
    }

    let select = null;
    if (snapshot.windowKey) {
      const selector = '[data-manual-window-key="' + snapshot.windowKey + '"] '
        + 'select[data-manual-boundary="' + snapshot.boundary + '"][data-manual-part="' + snapshot.part + '"]';
      select = manualDaysContainer.querySelector(selector);
    }
    if (!select) {
      const fallbackSelector = '[data-manual-day-index="' + snapshot.dayIndex + '"]'
        + '[data-manual-start-minutes="' + snapshot.startMinutes + '"]'
        + '[data-manual-end-minutes="' + snapshot.endMinutes + '"] '
        + 'select[data-manual-boundary="' + snapshot.boundary + '"][data-manual-part="' + snapshot.part + '"]';
      select = manualDaysContainer.querySelector(fallbackSelector);
    }
    if (!select) {
      return;
    }

    window.scrollTo(snapshot.windowScrollX, snapshot.windowScrollY);
    select.focus({ preventScroll: true });
  }

  function createDefaultWindow(dayIndex) {
    const dayWindows = workingWindows.filter(function (windowItem) {
      return windowItem.dayIndex === dayIndex;
    }).sort(compareWindows);
    let startMinutes = 9 * 60;
    if (dayWindows.length) {
      startMinutes = dayWindows[dayWindows.length - 1].endMinutes;
    }
    startMinutes = Math.max(0, Math.min(boardMinutes - defaultManualDurationMinutes, snapMinutes(startMinutes)));
    return {
      id: null,
      key: 'temp-' + (++tempId),
      dayIndex: dayIndex,
      startMinutes: startMinutes,
      endMinutes: Math.min(boardMinutes, startMinutes + defaultManualDurationMinutes),
      notes: '',
    };
  }

  function renderManualEditor() {
    if (!manualDaysContainer) {
      return;
    }

    manualDaysContainer.replaceChildren();
    weekdayNames.forEach(function (dayName, dayIndex) {
      const dayWindows = workingWindows.filter(function (windowItem) {
        return windowItem.dayIndex === dayIndex;
      }).sort(compareWindows);

      const daySection = document.createElement('section');
      daySection.className = 'availability-day-editor';

      const header = document.createElement('div');
      header.className = 'availability-day-editor__header';

      const title = document.createElement('div');
      title.className = 'availability-day-editor__title';
      const strong = document.createElement('strong');
      strong.textContent = dayName;
      title.appendChild(strong);
      const summary = document.createElement('span');
      summary.className = 'subtle-text';
      summary.textContent = dayWindows.length
        ? dayWindows.length + ' saved block' + (dayWindows.length === 1 ? '' : 's')
        : 'No availability saved yet';
      title.appendChild(summary);
      header.appendChild(title);

      const addButton = document.createElement('button');
      addButton.type = 'button';
      addButton.className = 'btn btn-secondary btn-small';
      addButton.dataset.manualAddDay = String(dayIndex);
      addButton.textContent = '+';
      addButton.setAttribute('aria-label', 'Add availability block for ' + dayName);
      header.appendChild(addButton);
      daySection.appendChild(header);

      const rows = document.createElement('div');
      rows.className = 'availability-day-editor__rows';
      if (!dayWindows.length) {
        const empty = document.createElement('p');
        empty.className = 'subtle-text';
        empty.textContent = 'No blocks saved for this day yet.';
        rows.appendChild(empty);
      } else {
        dayWindows.forEach(function (windowItem) {
          rows.appendChild(buildManualRow(windowItem));
        });
      }
      daySection.appendChild(rows);
      manualDaysContainer.appendChild(daySection);
    });
  }

  function renderBoard(focusOverride) {
    const focusSnapshot = focusOverride || pendingFocusRestore || captureManualFocus();
    pendingFocusRestore = null;

    board.querySelectorAll('[data-day-blocks]').forEach(function (blockHost) {
      const lane = blockHost.closest('.availability-board__lane');
      const dayIndex = Number(lane.dataset.dayIndex);
      blockHost.replaceChildren();
      workingWindows.filter(function (windowItem) {
        return windowItem.dayIndex === dayIndex;
      }).sort(compareWindows).forEach(function (windowItem) {
        blockHost.appendChild(buildBlock(windowItem));
      });
    });

    updateAvailabilitySummary(workingWindows);
    renderManualEditor();

    if (focusSnapshot) {
      requestAnimationFrame(function () {
        restoreManualFocus(focusSnapshot);
      });
    }
  }

  function snapMinutes(rawMinutes) {
    return Math.round(rawMinutes / slotMinutes) * slotMinutes;
  }

  function findLaneFromPoint(clientX, clientY) {
    const target = document.elementFromPoint(clientX, clientY);
    return target ? target.closest('.availability-board__lane') : null;
  }

  function minuteFromPointer(event, lane) {
    const rect = lane.getBoundingClientRect();
    const ratio = rect.width <= 0 ? 0 : (event.clientX - rect.left) / rect.width;
    const boundedRatio = Math.max(0, Math.min(1, ratio));
    return snapMinutes(boundedRatio * boardMinutes);
  }

  function getWindowByKey(key) {
    return workingWindows.find(function (windowItem) {
      return windowItem.key === key;
    }) || null;
  }

  function hasOverlaps(source) {
    const sortedWindows = source.slice().sort(compareWindows);
    for (let index = 1; index < sortedWindows.length; index += 1) {
      const previous = sortedWindows[index - 1];
      const current = sortedWindows[index];
      if (previous.dayIndex === current.dayIndex && current.startMinutes < previous.endMinutes) {
        return true;
      }
    }
    return false;
  }

  function beginInteraction(nextInteraction) {
    interaction = nextInteraction;
    board.classList.add('availability-board--dragging');
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', cancelInteraction);
  }

  function resetInteractionState() {
    board.classList.remove('availability-board--dragging');
    window.removeEventListener('pointermove', handlePointerMove);
    window.removeEventListener('pointerup', handlePointerUp);
    window.removeEventListener('pointercancel', cancelInteraction);
    interaction = null;
  }

  function finishInteraction(shouldSave) {
    resetInteractionState();

    if (!shouldSave) {
      workingWindows = cloneWindows(committedWindows);
      renderBoard();
      return;
    }

    if (hasOverlaps(workingWindows)) {
      workingWindows = cloneWindows(committedWindows);
      renderBoard();
      setStatus('Availability windows cannot overlap on the same day.', true, true);
      return;
    }

    if (JSON.stringify(serializeWindows(workingWindows)) === JSON.stringify(serializeWindows(committedWindows))) {
      renderBoard();
      return;
    }

    saveWindows();
  }

  function cancelInteraction() {
    finishInteraction(false);
  }

  function updateDraggedWindow(event) {
    if (!interaction) {
      return;
    }

    const targetWindow = getWindowByKey(interaction.key);
    if (!targetWindow) {
      return;
    }

    if (interaction.mode === 'create') {
      const currentMinutes = minuteFromPointer(event, interaction.lane);
      let startMinutes = Math.min(interaction.anchorMinutes, currentMinutes);
      let endMinutes = Math.max(interaction.anchorMinutes, currentMinutes);
      if (endMinutes - startMinutes < slotMinutes) {
        if (currentMinutes >= interaction.anchorMinutes) {
          endMinutes = Math.min(boardMinutes, startMinutes + slotMinutes);
        } else {
          startMinutes = Math.max(0, endMinutes - slotMinutes);
        }
      }
      targetWindow.startMinutes = Math.max(0, Math.min(boardMinutes - slotMinutes, startMinutes));
      targetWindow.endMinutes = Math.max(targetWindow.startMinutes + slotMinutes, Math.min(boardMinutes, endMinutes));
      renderBoard();
      return;
    }

    if (interaction.mode === 'move') {
      const lane = findLaneFromPoint(event.clientX, event.clientY) || interaction.lane;
      const duration = interaction.durationMinutes;
      const pointerMinutes = minuteFromPointer(event, lane);
      const nextStart = Math.max(0, Math.min(boardMinutes - duration, pointerMinutes - interaction.offsetMinutes));
      targetWindow.dayIndex = Number(lane.dataset.dayIndex);
      targetWindow.startMinutes = nextStart;
      targetWindow.endMinutes = nextStart + duration;
      renderBoard();
      return;
    }

    if (interaction.mode === 'resize-start') {
      const pointerMinutes = minuteFromPointer(event, interaction.lane);
      targetWindow.startMinutes = Math.max(0, Math.min(targetWindow.endMinutes - slotMinutes, pointerMinutes));
      renderBoard();
      return;
    }

    if (interaction.mode === 'resize-end') {
      const pointerMinutes = minuteFromPointer(event, interaction.lane);
      targetWindow.endMinutes = Math.max(targetWindow.startMinutes + slotMinutes, Math.min(boardMinutes, pointerMinutes));
      renderBoard();
    }
  }

  function handlePointerMove(event) {
    if (!interaction) {
      return;
    }

    event.preventDefault();
    updateDraggedWindow(event);
  }

  function handlePointerUp(event) {
    if (!interaction) {
      return;
    }

    event.preventDefault();
    updateDraggedWindow(event);
    finishInteraction(true);
  }

  function saveWindows() {
    if (!syncForm || !windowsInput || isSaving) {
      return;
    }

    const focusSnapshot = pendingFocusRestore || captureManualFocus();

    isSaving = true;
    windowsInput.value = JSON.stringify(serializeWindows(workingWindows));
    setStatus('Saving...', false, true);
    updateAvailabilitySummary(workingWindows);

    fetch(syncForm.action, {
      method: 'POST',
      body: new FormData(syncForm),
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    }).then(function (response) {
      return response.json().catch(function () {
        return { ok: false, error: 'Unable to save weekly availability right now.' };
      }).then(function (payload) {
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || 'Unable to save weekly availability right now.');
        }
        return payload;
      });
    }).then(function (payload) {
      committedWindows = normalizeWindows(payload.windows || []);
      workingWindows = cloneWindows(committedWindows);
      pendingFocusRestore = focusSnapshot;
      renderBoard();
      setStatus(payload.message || 'Availability updated.', false);
    }).catch(function (error) {
      workingWindows = cloneWindows(committedWindows);
      pendingFocusRestore = focusSnapshot;
      renderBoard();
      setStatus(error.message || 'Unable to save weekly availability right now.', true, true);
    }).finally(function () {
      isSaving = false;
    });
  }

  board.addEventListener('click', function (event) {
    const copyToNextButton = event.target.closest('[data-availability-copy-to-next]');
    if (copyToNextButton && !isSaving) {
      const sourceDayIndex = Number(copyToNextButton.dataset.availabilityCopyToNext);
      const targetDayIndex = (sourceDayIndex + 1 + weekdayNames.length) % weekdayNames.length;
      if (!Number.isNaN(sourceDayIndex)) {
        duplicateDayWindows(sourceDayIndex, targetDayIndex);
        saveWindows();
      }
      return;
    }

    const copyFromPreviousButton = event.target.closest('[data-availability-copy-from-previous]');
    if (copyFromPreviousButton && !isSaving) {
      const targetDayIndex = Number(copyFromPreviousButton.dataset.availabilityCopyFromPrevious);
      const sourceDayIndex = (targetDayIndex - 1 + weekdayNames.length) % weekdayNames.length;
      if (!Number.isNaN(targetDayIndex)) {
        duplicateDayWindows(sourceDayIndex, targetDayIndex);
        saveWindows();
      }
      return;
    }

    const deleteButton = event.target.closest('[data-availability-delete]');
    if (!deleteButton || isSaving) {
      return;
    }

    const block = deleteButton.closest('.availability-block');
    if (!block) {
      return;
    }

    event.preventDefault();
    const focusSnapshot = createScrollSnapshot();
    workingWindows = workingWindows.filter(function (windowItem) {
      return windowItem.key !== block.dataset.windowKey;
    });
    renderBoard(focusSnapshot);
    pendingFocusRestore = focusSnapshot;
    saveWindows();
  });

  if (clearButton) {
    clearButton.addEventListener('click', function () {
      if (isSaving || workingWindows.length === 0) {
        return;
      }

      const focusSnapshot = createScrollSnapshot();
      workingWindows = [];
      renderBoard(focusSnapshot);
      pendingFocusRestore = focusSnapshot;
      saveWindows();
    });
  }

  if (manualDaysContainer) {
    manualDaysContainer.addEventListener('click', function (event) {
      const addButton = event.target.closest('[data-manual-add-day]');
      if (addButton && !isSaving) {
        const dayIndex = Number(addButton.dataset.manualAddDay);
        const nextWindow = createDefaultWindow(dayIndex);
        const focusSnapshot = createManualFocusSnapshot({
          windowKey: nextWindow.key,
          dayIndex: nextWindow.dayIndex,
          startMinutes: nextWindow.startMinutes,
          endMinutes: nextWindow.endMinutes,
          boundary: 'start',
          part: 'hour',
        });
        workingWindows = cloneWindows(committedWindows);
        workingWindows.push(nextWindow);
        workingWindows.sort(compareWindows);
        renderBoard(focusSnapshot);
        pendingFocusRestore = focusSnapshot;
        saveWindows();
        return;
      }

      const removeButton = event.target.closest('[data-manual-remove]');
      if (removeButton && !isSaving) {
        const windowKey = removeButton.dataset.manualRemove;
        const row = removeButton.closest('[data-manual-window-key]');
        let focusSnapshot = createScrollSnapshot();

        if (row) {
          const siblingRows = Array.from(row.parentElement.querySelectorAll('[data-manual-window-key]'));
          const rowIndex = siblingRows.findIndex(function (candidate) {
            return candidate.dataset.manualWindowKey === windowKey;
          });
          const nextRow = siblingRows[rowIndex + 1] || siblingRows[rowIndex - 1];
          if (nextRow) {
            focusSnapshot = createManualFocusSnapshot({
              windowKey: nextRow.dataset.manualWindowKey,
              dayIndex: nextRow.dataset.manualDayIndex,
              startMinutes: nextRow.dataset.manualStartMinutes,
              endMinutes: nextRow.dataset.manualEndMinutes,
              boundary: 'start',
              part: 'hour',
            });
          } else {
            focusSnapshot = createManualButtonSnapshot(row.dataset.manualDayIndex);
          }
        }

        workingWindows = workingWindows.filter(function (windowItem) {
          return windowItem.key !== windowKey;
        });
        renderBoard(focusSnapshot);
        pendingFocusRestore = focusSnapshot;
        saveWindows();
      }
    });

    manualDaysContainer.addEventListener('change', function (event) {
      const select = event.target.closest('select[data-manual-boundary]');
      if (!select || isSaving) {
        return;
      }

      const row = select.closest('[data-manual-window-key]');
      if (!row) {
        return;
      }

      const windowItem = getWindowByKey(row.dataset.manualWindowKey);
      if (!windowItem) {
        return;
      }

      const focusSnapshot = captureManualFocus();

      let startMinutes = (
        Number(row.querySelector('select[data-manual-boundary="start"][data-manual-part="hour"]').value) * 60
        + Number(row.querySelector('select[data-manual-boundary="start"][data-manual-part="minute"]').value)
      );
      let endMinutes = (
        Number(row.querySelector('select[data-manual-boundary="end"][data-manual-part="hour"]').value) * 60
        + Number(row.querySelector('select[data-manual-boundary="end"][data-manual-part="minute"]').value)
      );

      if (endMinutes <= startMinutes) {
        if (select.dataset.manualBoundary === 'start') {
          endMinutes = Math.min(boardMinutes, startMinutes + defaultManualDurationMinutes);
          if (endMinutes <= startMinutes) {
            startMinutes = Math.max(0, endMinutes - defaultManualDurationMinutes);
          }
        } else {
          startMinutes = Math.max(0, endMinutes - defaultManualDurationMinutes);
        }
      }

      windowItem.startMinutes = Math.max(0, Math.min(boardMinutes - slotMinutes, snapMinutes(startMinutes)));
      windowItem.endMinutes = Math.max(windowItem.startMinutes + slotMinutes, Math.min(boardMinutes, snapMinutes(endMinutes)));
      renderBoard(focusSnapshot);
      pendingFocusRestore = focusSnapshot;
      saveWindows();
    });
  }

  board.addEventListener('pointerdown', function (event) {
    if (isSaving || event.button !== 0) {
      return;
    }

    const deleteButton = event.target.closest('[data-availability-delete]');
    if (deleteButton) {
      return;
    }

    const handle = event.target.closest('[data-availability-handle]');
    const block = event.target.closest('.availability-block');

    if (handle && block) {
      const key = block.dataset.windowKey;
      const targetWindow = getWindowByKey(key);
      if (!targetWindow) {
        return;
      }

      event.preventDefault();
      beginInteraction({
        key: key,
        mode: handle.dataset.availabilityHandle === 'start' ? 'resize-start' : 'resize-end',
        lane: block.closest('.availability-board__lane'),
      });
      return;
    }

    if (block) {
      const key = block.dataset.windowKey;
      const targetWindow = getWindowByKey(key);
      const lane = block.closest('.availability-board__lane');
      if (!targetWindow || !lane) {
        return;
      }

      event.preventDefault();
      beginInteraction({
        key: key,
        mode: 'move',
        lane: lane,
        durationMinutes: targetWindow.endMinutes - targetWindow.startMinutes,
        offsetMinutes: minuteFromPointer(event, lane) - targetWindow.startMinutes,
      });
      return;
    }

    const lane = event.target.closest('.availability-board__lane');
    if (!lane) {
      return;
    }

    const anchorMinutes = minuteFromPointer(event, lane);
    const key = 'temp-' + (++tempId);
    workingWindows = cloneWindows(committedWindows);
    workingWindows.push({
      id: null,
      key: key,
      dayIndex: Number(lane.dataset.dayIndex),
      startMinutes: Math.max(0, Math.min(boardMinutes - slotMinutes, anchorMinutes)),
      endMinutes: Math.max(slotMinutes, Math.min(boardMinutes, anchorMinutes + slotMinutes)),
      notes: '',
    });
    renderBoard();
    event.preventDefault();
    beginInteraction({
      key: key,
      mode: 'create',
      lane: lane,
      anchorMinutes: anchorMinutes,
    });
  });

  renderBoard();
})();
