// Extracted from app/templates/main/quote_request.html — keep behaviour identical.
(function () {
  const form = document.querySelector('.quote-form');
  const input = document.querySelector('#photos') || document.querySelector('input[name="photos"]');
  const preview = document.querySelector('#photo-preview');
  const tokenInput = form ? form.querySelector('input[name="recaptcha_token"]') : null;
  const submitButton = form ? form.querySelector('button[type="submit"], input[type="submit"]') : null;
  const clientError = document.querySelector('#recaptcha-client-error');
  const siteKey = form ? form.dataset.recaptchaSiteKey : '';
  const recaptchaAction = form ? form.dataset.recaptchaAction : '';
  let verifyingRecaptcha = false;

  const formatBytes = (bytes) => {
    if (bytes < 1024) return `${bytes} bytes`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const updatePreview = () => {
    if (!input || !preview) {
      return;
    }

    const files = input.files;
    if (!files || files.length === 0) {
      preview.textContent = 'No files selected.';
      return;
    }

    let total = 0;
    Array.from(files).forEach((file) => {
      total += file.size;
    });

    preview.textContent = `Selected ${files.length} file${files.length === 1 ? '' : 's'} · ${formatBytes(total)} total.`;
  };

  const showRecaptchaError = (message) => {
    if (!clientError) {
      return;
    }

    clientError.textContent = message;
    clientError.hidden = !message;
  };

  if (form && siteKey && recaptchaAction && tokenInput) {
    form.addEventListener('submit', (event) => {
      if (tokenInput.value) {
        return;
      }

      if (!window.grecaptcha) {
        event.preventDefault();
        showRecaptchaError("Spam protection is still loading. Please wait a moment and try again.");
        return;
      }

      event.preventDefault();
      if (verifyingRecaptcha) {
        return;
      }

      verifyingRecaptcha = true;
      showRecaptchaError('');
      if (submitButton) {
        submitButton.disabled = true;
      }

      grecaptcha.ready(() => {
        grecaptcha.execute(siteKey, {action: recaptchaAction}).then((token) => {
          tokenInput.value = token;
          verifyingRecaptcha = false;
          if (submitButton) {
            submitButton.disabled = false;
          }
          if (form.requestSubmit && submitButton) {
            form.requestSubmit(submitButton);
            return;
          }
          form.submit();
        }).catch(() => {
          verifyingRecaptcha = false;
          if (submitButton) {
            submitButton.disabled = false;
          }
          showRecaptchaError("We couldn't verify the spam protection check. Please try again.");
        });
      });
    });
  }

  if (input) {
    input.addEventListener('change', updatePreview);
  }
  updatePreview();
})();
