// Shared behaviour for every page: the confirm dialog for destructive actions.
// Extracted from app/templates/base.html — keep behaviour identical.
    (function () {
      const dialog = document.getElementById('confirm-dialog');
      const message = dialog ? dialog.querySelector('.confirm-dialog__message') : null;
      const acceptButton = dialog ? dialog.querySelector('[data-confirm-accept]') : null;
      const cancelButton = dialog ? dialog.querySelector('[data-confirm-cancel]') : null;
      let pendingForm = null;

      function closeDialog() {
        if (!dialog || !dialog.open) {
          return;
        }
        dialog.close();
      }

      document.addEventListener('submit', function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
          return;
        }

        const confirmText = form.dataset.confirmText;
        if (!confirmText) {
          return;
        }

        if (form.dataset.confirmed === 'true') {
          form.dataset.confirmed = 'false';
          return;
        }

        if (!dialog || typeof dialog.showModal !== 'function' || !message || !acceptButton || !cancelButton) {
          if (!window.confirm(confirmText)) {
            event.preventDefault();
          }
          return;
        }

        event.preventDefault();
        pendingForm = form;
        message.textContent = confirmText;
        dialog.showModal();
      });

      if (cancelButton) {
        cancelButton.addEventListener('click', function () {
          pendingForm = null;
          closeDialog();
        });
      }

      if (acceptButton) {
        acceptButton.addEventListener('click', function () {
          if (!pendingForm) {
            closeDialog();
            return;
          }

          const formToSubmit = pendingForm;
          pendingForm = null;
          formToSubmit.dataset.confirmed = 'true';
          closeDialog();
          if (formToSubmit.requestSubmit) {
            formToSubmit.requestSubmit();
            return;
          }
          HTMLFormElement.prototype.submit.call(formToSubmit);
        });
      }

      if (dialog) {
        dialog.addEventListener('cancel', function () {
          pendingForm = null;
        });
        dialog.addEventListener('close', function () {
          if (dialog.returnValue !== 'default') {
            dialog.returnValue = 'default';
          }
        });
      }
    })();
    
