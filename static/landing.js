/* Landing page scroll reveals. Progressive enhancement only: the CSS hides
 * .reveal elements solely under `@media (scripting: enabled)`, so with this
 * file blocked or unsupported the page renders fully visible. */
(function () {
  'use strict';

  var els = document.querySelectorAll('.reveal');

  if (!('IntersectionObserver' in window)) {
    els.forEach(function (el) { el.classList.add('is-in'); });
    return;
  }

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-in');
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.18 });

  els.forEach(function (el) { io.observe(el); });
})();
