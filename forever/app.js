// Forever launch prep: show launch in the viewer's own time zone and count down
// to it. Progressive enhancement only; the page reads fine with JS off. Stores
// nothing and talks to no server.
(function () {
  "use strict";
  var local = document.getElementById("launch-local");
  var count = document.getElementById("countdown");
  if (!local || !count) return;
  var launch = new Date(local.getAttribute("data-utc"));
  if (isNaN(launch.getTime())) return;

  try {
    var fmt = new Intl.DateTimeFormat(undefined, {
      weekday: "long", month: "long", day: "numeric",
      hour: "numeric", minute: "2-digit", timeZoneName: "short"
    });
    local.textContent = "Your time: " + fmt.format(launch);
    local.hidden = false;
  } catch (e) { /* old browser: the PST line stands on its own */ }

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function tick() {
    var ms = launch.getTime() - Date.now();
    if (ms <= 0) {
      count.textContent = "It's live. Log in.";
      count.hidden = false;
      return;
    }
    var s = Math.floor(ms / 1000);
    var d = Math.floor(s / 86400); s -= d * 86400;
    var h = Math.floor(s / 3600); s -= h * 3600;
    var m = Math.floor(s / 60); s -= m * 60;
    count.textContent = d + "d " + pad(h) + "h " + pad(m) + "m " + pad(s) + "s";
    count.hidden = false;
    setTimeout(tick, 1000);
  }
  tick();
})();
