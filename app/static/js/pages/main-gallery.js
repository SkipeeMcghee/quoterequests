// Extracted from app/templates/main/gallery.html — keep behaviour identical.
(function () {
  const lightbox = document.getElementById('gallery-public-lightbox');
  const lightboxImage = lightbox ? lightbox.querySelector('[data-gallery-public-image]') : null;
  const lightboxTitle = lightbox ? lightbox.querySelector('[data-gallery-public-title]') : null;
  const lightboxCaption = lightbox ? lightbox.querySelector('[data-gallery-public-caption]') : null;
  const lightboxService = lightbox ? lightbox.querySelector('[data-gallery-public-service]') : null;

  function syncPageScrollLock() {
    document.body.classList.toggle('gallery-popup-open', Boolean(lightbox && lightbox.hasAttribute('open')));
  }

  function openLightbox(trigger) {
    if (!lightbox || !lightboxImage || !lightboxTitle || !trigger) {
      return;
    }

    const service = trigger.dataset.galleryPublicService || '';
    const caption = trigger.dataset.galleryPublicCaption || '';

    lightboxImage.src = trigger.dataset.galleryPublicSrc || '';
    lightboxImage.alt = trigger.dataset.galleryPublicAlt || '';
    lightboxTitle.textContent = trigger.dataset.galleryPublicTitle || '';

    if (lightboxCaption) {
      lightboxCaption.textContent = caption;
      lightboxCaption.hidden = !caption;
    }

    if (lightboxService) {
      lightboxService.textContent = service;
      lightboxService.hidden = !service;
    }

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

  document.querySelectorAll('[data-gallery-public-open]').forEach(function (button) {
    button.addEventListener('click', function () {
      openLightbox(button);
    });
  });

  if (lightbox) {
    const closeButton = lightbox.querySelector('[data-gallery-public-close]');
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
