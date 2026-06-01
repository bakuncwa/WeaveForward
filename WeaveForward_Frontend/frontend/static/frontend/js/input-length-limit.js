(function () {
  const maxLength = Number(window.WF_TEXT_FIELD_MAX_LENGTH || 1000);
  const numberMaxLength = 50;
  const skippedTypes = new Set([
    'button',
    'checkbox',
    'color',
    'date',
    'datetime-local',
    'file',
    'hidden',
    'image',
    'month',
    'radio',
    'range',
    'reset',
    'submit',
    'time',
    'week',
  ]);

  function capField(field) {
    const tagName = field.tagName.toLowerCase();
    const type = (field.getAttribute('type') || 'text').toLowerCase();

    if (tagName === 'input' && skippedTypes.has(type)) return;
    if (field.readOnly || field.disabled) return;

    if (tagName === 'input' && type === 'number') {
      if (field.dataset.wfLengthCapAttached) return;
      field.dataset.wfLengthCapAttached = 'true';
      field.addEventListener('input', function () {
        if (field.value.length > numberMaxLength) {
          field.value = field.value.slice(0, numberMaxLength);
        }
      });
      return;
    }

    const currentMax = Number(field.getAttribute('maxlength'));
    if (!currentMax || currentMax > maxLength) {
      field.setAttribute('maxlength', String(maxLength));
    }
  }

  function capFields(root) {
    if (root.matches?.('input, textarea')) capField(root);
    root.querySelectorAll?.('input, textarea').forEach(capField);
  }

  function initInputLengthLimit() {
    capFields(document);

    new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (node.nodeType === Node.ELEMENT_NODE) capFields(node);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initInputLengthLimit);
  } else {
    initInputLengthLimit();
  }
})();
