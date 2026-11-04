// Extracted from app/templates/admin/recurring_work_form.html — keep behaviour identical.
    (function () {
      var forms = document.querySelectorAll('[data-recurring-rule-form]');
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
    }());
  
