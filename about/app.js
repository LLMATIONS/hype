/* about/app.js — convert the canonical raid schedule into the viewer's local
 * time zone. Progressive enhancement: the Central and Realm columns are static
 * in the HTML and read fine with JS off; this only fills the "Your time" column,
 * the detected-zone label, and the "next raid" line.
 *
 * Canonical schedule: Tuesday & Thursday, 8:00 PM America/Chicago (Central).
 * Realm/server time runs one hour behind Central, i.e. America/Denver (Mountain),
 * which stays Central-minus-one through every DST change. All conversions use the
 * Intl time-zone database, so daylight-saving shifts are handled for free.
 */
(function () {
  "use strict";
  if (!window.Intl || !Intl.DateTimeFormat) return; // ancient browser: leave the static fallback

  var SOURCE_TZ = "America/Chicago"; // raids are scheduled in Central
  var RAID_HOUR = 20;                // 8:00 PM
  var RAID_MIN = 0;
  var RAID_DAYS = [2, 4];            // 0=Sun … 2=Tue, 4=Thu
  var WD = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

  // Offset (ms) of `tz` at a given instant: how far that zone's wall clock is
  // ahead of UTC. Derived by reading the instant back out in the target zone.
  function offsetMs(tz, date) {
    var dtf = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hour12: false,
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit"
    });
    var p = {};
    dtf.formatToParts(date).forEach(function (x) { if (x.type !== "literal") p[x.type] = x.value; });
    var asUTC = Date.UTC(+p.year, +p.month - 1, +p.day, (+p.hour) % 24, +p.minute, +p.second);
    return asUTC - date.getTime();
  }

  // The UTC instant whose wall clock in `tz` is y-m(0-based)-d at h:min.
  function zonedInstant(tz, y, m, d, h, min) {
    var guess = Date.UTC(y, m, d, h, min);
    var off = offsetMs(tz, new Date(guess));
    off = offsetMs(tz, new Date(guess - off)); // second pass settles DST edges
    return new Date(guess - off);
  }

  // Next time `weekday` lands at the raid hour in Central, at or after `now`
  // (with a 3h grace so the row/banner stays put while a raid is in progress).
  function nextRaid(weekday, now) {
    var fmt = new Intl.DateTimeFormat("en-US", {
      timeZone: SOURCE_TZ, weekday: "short",
      year: "numeric", month: "2-digit", day: "2-digit"
    });
    for (var i = 0; i < 14; i++) {
      var probe = new Date(now.getTime() + i * 86400000);
      var p = {};
      fmt.formatToParts(probe).forEach(function (x) { if (x.type !== "literal") p[x.type] = x.value; });
      if (WD[p.weekday] !== weekday) continue;
      var inst = zonedInstant(SOURCE_TZ, +p.year, +p.month - 1, +p.day, RAID_HOUR, RAID_MIN);
      if (inst.getTime() >= now.getTime() - 3 * 3600000) return inst;
    }
    return null;
  }

  function fmtLocal(date) {
    return new Intl.DateTimeFormat([], {
      weekday: "short", hour: "numeric", minute: "2-digit"
    }).format(date);
  }

  function zoneAbbrev(date) {
    try {
      var parts = new Intl.DateTimeFormat([], { timeZoneName: "short" }).formatToParts(date);
      for (var i = 0; i < parts.length; i++) {
        if (parts[i].type === "timeZoneName") return parts[i].value;
      }
    } catch (e) { /* fall through */ }
    return "";
  }

  function humanZone() {
    try {
      var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      return tz ? tz.split("/").pop().replace(/_/g, " ") : "";
    } catch (e) { return ""; }
  }

  function relative(ms) {
    var mins = Math.round(ms / 60000);
    if (mins < 60) return "in " + mins + " min";
    var hrs = Math.floor(mins / 60);
    if (hrs < 24) return "in " + hrs + "h " + (mins % 60) + "m";
    var days = Math.floor(hrs / 24);
    return "in " + days + "d " + (hrs % 24) + "h";
  }

  function run() {
    var now = new Date();
    var abbrev = zoneAbbrev(now);
    var zname = humanZone();

    var label = document.getElementById("tzlabel");
    if (label && abbrev) label.textContent = "(" + abbrev + ")";

    // Fill each "Your time" cell with its next occurrence, local.
    var cells = document.querySelectorAll(".you[data-day]");
    var soonest = null;
    Array.prototype.forEach.call(cells, function (cell) {
      var day = +cell.getAttribute("data-day");
      var inst = nextRaid(day, now);
      if (!inst) return;
      cell.textContent = fmtLocal(inst);
      if (!soonest || inst.getTime() < soonest.getTime()) soonest = inst;
    });

    var tzline = document.getElementById("tzline");
    if (tzline) {
      tzline.innerHTML = "Realm time runs one hour behind Central. “Your time” is your browser's zone" +
        (zname ? ", <b>" + zname + "</b>" : "") + " — it follows daylight saving automatically.";
    }

    if (soonest) {
      var banner = document.getElementById("nextraid");
      if (banner) {
        banner.innerHTML = "<b>Next raid:</b> " + fmtLocal(soonest) +
          (abbrev ? " " + abbrev : "") + " · " + relative(soonest.getTime() - now.getTime());
        banner.hidden = false;
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
