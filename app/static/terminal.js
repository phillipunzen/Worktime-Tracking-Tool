(function () {
  // Bildschirmtastatur: schreibt in das zuletzt fokussierte Feld
  var fields = Array.prototype.slice.call(document.querySelectorAll("[data-keypad]"));
  var active = fields[0];
  fields.forEach(function (f) { f.addEventListener("focus", function () { active = f; }); });

  document.querySelectorAll("[data-key]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!active) return;
      var key = btn.getAttribute("data-key");
      if (key === "back") active.value = active.value.slice(0, -1);
      else if (key === "clear") active.value = "";
      else if (!active.maxLength || active.maxLength < 0 || active.value.length < active.maxLength) active.value += key;
      resetIdle();
    });
  });

  // Enter in der Personalnummer springt zur PIN (Ausweisleser senden meist Enter)
  var badge = document.getElementById("badge");
  var pin = document.getElementById("pin");
  if (badge && pin) {
    badge.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !pin.value) { e.preventDefault(); pin.focus(); }
    });
  }
  // "Weiter" ohne PIN -> erst zur PIN springen
  var form = document.getElementById("login-form");
  if (form && badge) {
    form.addEventListener("submit", function (e) {
      if (!badge.value) { e.preventDefault(); badge.focus(); return; }
      if (pin && !pin.value) { e.preventDefault(); pin.focus(); }
    });
  }

  // Automatisch zurück zum Startbildschirm
  var target = document.body.getAttribute("data-autoreturn");
  var after = parseInt(document.body.getAttribute("data-autoreturn-after") || "0", 10);
  var timer = null;
  function resetIdle() {
    if (timer) clearTimeout(timer);
    if (target && after > 0) timer = setTimeout(function () { window.location.href = target; }, after * 1000);
  }
  document.addEventListener("pointerdown", resetIdle);
  resetIdle();

  // Anmeldemaske nach 30 s Inaktivität leeren (falls jemand mitten in der Eingabe weggeht)
  if (form) {
    var clearTimer = null;
    var armClear = function () {
      if (clearTimer) clearTimeout(clearTimer);
      clearTimer = setTimeout(function () { fields.forEach(function (f) { f.value = ""; }); if (badge) badge.focus(); }, 30000);
    };
    document.addEventListener("pointerdown", armClear);
    document.addEventListener("keydown", armClear);
  }

  // Doppeltes Absenden verhindern
  document.querySelectorAll("form").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (e.defaultPrevented) return;
      if (f.dataset.sent) { e.preventDefault(); return; }
      f.dataset.sent = "1";
    });
  });
})();
