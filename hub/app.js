// Hub: keep the dates on the landing page current on their own.
// - [data-at]   an exact instant (UTC). Gets "in 4 days", "in 5 hours",
//               then its data-done label once it has passed.
// - [data-day]  a calendar date with no announced hour (YYYY-MM-DD, Pacific).
//               Gets "in N days", "tomorrow", "today", then data-done.
// - [data-flip-at] swaps its text for data-after once that instant passes.
// Progressive enhancement only; the static text reads fine with JS off.
// Stores nothing and talks to no server.
(function () {
  "use strict";
  var HOUR = 3600000, DAY = 86400000;

  function instant(v) {
    var t = v ? new Date(v).getTime() : NaN;
    return isNaN(t) ? null : t;
  }

  // Today's date in Pacific as a UTC-midnight timestamp, so two dates
  // subtract to a whole number of days. null if Intl time zones are missing.
  var pacific = null;
  try {
    pacific = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles", year: "numeric", month: "numeric", day: "numeric"
    });
  } catch (e) { /* old browser: data-day rows keep their static text */ }

  function pacificToday(now) {
    var p = {};
    pacific.formatToParts(now).forEach(function (x) { p[x.type] = +x.value; });
    return Date.UTC(p.year, p.month - 1, p.day);
  }

  function relAt(target, now, done) {
    var ms = target - now;
    if (ms <= 0) return [done, true];
    if (ms < HOUR) return ["in " + Math.max(1, Math.floor(ms / 60000)) + " min", false];
    if (ms < DAY) {
      var h = Math.floor(ms / HOUR);
      return ["in " + h + (h === 1 ? " hour" : " hours"), false];
    }
    var d = Math.floor(ms / DAY);
    return ["in " + d + (d === 1 ? " day" : " days"), false];
  }

  function relDay(ymd, now, done) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd || "");
    if (!m || !pacific) return null;
    var n = Math.round((Date.UTC(+m[1], +m[2] - 1, +m[3]) - pacificToday(now)) / DAY);
    if (n < 0) return [done, true];
    if (n === 0) return ["today", false];
    if (n === 1) return ["tomorrow", false];
    return ["in " + n + " days", false];
  }

  function setRel(el, r) {
    var span = el.querySelector(".rel");
    if (!r) { if (span) span.parentNode.removeChild(span); return; }
    if (!span) {
      span = document.createElement("span");
      el.appendChild(span);
    }
    span.className = "rel" + (r[1] ? " rel-done" : "");
    if (span.textContent !== r[0]) span.textContent = r[0];
  }

  function tick() {
    var now = Date.now();
    var els = document.querySelectorAll("[data-at]");
    for (var i = 0; i < els.length; i++) {
      var t = instant(els[i].getAttribute("data-at"));
      setRel(els[i], t === null ? null : relAt(t, now, els[i].getAttribute("data-done") || "passed"));
    }
    els = document.querySelectorAll("[data-day]");
    for (i = 0; i < els.length; i++) {
      setRel(els[i], relDay(els[i].getAttribute("data-day"), now, els[i].getAttribute("data-done") || "passed"));
    }
    els = document.querySelectorAll("[data-flip-at]");
    for (i = 0; i < els.length; i++) {
      var f = instant(els[i].getAttribute("data-flip-at"));
      var after = els[i].getAttribute("data-after");
      if (f !== null && after && now >= f && els[i].textContent !== after) els[i].textContent = after;
    }
    // Hour and minute granularity, so once a minute is plenty.
    setTimeout(tick, 60000);
  }
  tick();
})();
