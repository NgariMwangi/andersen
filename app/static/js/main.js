// HRMS Kenya - main JS (HTMX can be added for dynamic interactions)
document.addEventListener('DOMContentLoaded', function () {
  // Bootstrap tooltips if needed
  var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.forEach(function (el) { new bootstrap.Tooltip(el); });
});
