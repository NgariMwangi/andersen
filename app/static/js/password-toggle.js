/**
 * Show/hide password for inputs inside .password-wrap containers.
 */
(function () {
  function initWrap(wrap) {
    var input = wrap.querySelector('input[type="password"], input[type="text"].has-toggle');
    var btn = wrap.querySelector('.password-toggle-btn');
    var icon = btn && btn.querySelector('i');
    if (!input || !btn || !icon) return;

    btn.addEventListener('click', function () {
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      icon.classList.toggle('bi-eye', !show);
      icon.classList.toggle('bi-eye-slash', show);
      var label = show ? 'Hide password' : 'Show password';
      btn.setAttribute('aria-label', label);
      btn.setAttribute('title', label);
    });
  }

  function initAll() {
    document.querySelectorAll('.password-wrap').forEach(initWrap);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
