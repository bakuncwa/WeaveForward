document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.drop').forEach(zone => {
    const input = zone.querySelector('input[type="file"]') || zone.parentElement?.querySelector('input[type="file"]');
    if (!input) return;

    ['dragenter', 'dragover'].forEach(eventName => {
      zone.addEventListener(eventName, event => {
        event.preventDefault();
        zone.classList.add('drag-over');
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      zone.addEventListener(eventName, event => {
        event.preventDefault();
        zone.classList.remove('drag-over');
      });
    });

    zone.addEventListener('drop', event => {
      const files = event.dataTransfer?.files;
      if (!files?.length) return;
      input.files = files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
});
