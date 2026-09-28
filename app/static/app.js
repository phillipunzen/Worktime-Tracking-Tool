(function () {
  // Mobiles Menü
  var toggle = document.querySelector(".menu-toggle");
  var nav = document.querySelector(".nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  // Live-Uhr für laufende Arbeitszeit: data-base = bereits gebuchte Minuten heute,
  // data-since = Startzeit (ISO) des laufenden Segments
  var timers = document.querySelectorAll("[data-timer]");
  var serverNow = document.body.getAttribute("data-now");
  var offset = serverNow ? (new Date(serverNow).getTime() - Date.now()) : 0;

  function tick() {
    timers.forEach(function (el) {
      var base = parseInt(el.getAttribute("data-base") || "0", 10) * 60;
      var since = el.getAttribute("data-since");
      var seconds = base;
      if (since) {
        seconds += Math.max(0, Math.floor((Date.now() + offset - new Date(since).getTime()) / 1000));
      }
      var h = Math.floor(seconds / 3600);
      var m = Math.floor((seconds % 3600) / 60);
      var s = seconds % 60;
      el.textContent = h + ":" + pad(m) + (el.hasAttribute("data-seconds") ? ":" + pad(s) : "");
    });
  }
  if (timers.length) { tick(); setInterval(tick, 1000); }

  // Uhrzeit im Kopf der Stempelkarte
  var clock = document.querySelector("[data-clock]");
  if (clock) {
    var updateClock = function () {
      var d = new Date(Date.now() + offset);
      clock.textContent = pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
    };
    updateClock(); setInterval(updateClock, 1000);
  }

  // Sicherheitsabfragen
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) { e.preventDefault(); }
    });
  });

  // Berichtsfilter: Datumsfelder nur bei "Zeitraum" zeigen
  var period = document.getElementById("period");
  if (period) {
    var sync = function () {
      document.querySelectorAll("[data-custom]").forEach(function (el) {
        el.style.display = period.value === "custom" ? "" : "none";
      });
      document.querySelectorAll("[data-ref]").forEach(function (el) {
        el.style.display = period.value === "custom" ? "none" : "";
      });
    };
    period.addEventListener("change", sync); sync();
  }

  // Seite regelmäßig aktualisieren (Team-Übersicht)
  var refresh = document.body.getAttribute("data-refresh");
  if (refresh) { setTimeout(function () { window.location.reload(); }, parseInt(refresh, 10) * 1000); }
})();

// Verwaltungs-Dropdown schließen, wenn außerhalb geklickt wird
document.addEventListener("click", function (e) {
  document.querySelectorAll("details.nav-group[open]").forEach(function (d) {
    if (!d.contains(e.target)) d.removeAttribute("open");
  });
});
