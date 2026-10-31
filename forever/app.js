// Forever launch prep: show launch in the viewer's own time zone, count down
// to it, and keep the key-dates list current (past entries dim, the running
// one gets a "now" tag). After launch the countdown points at raid night.
// Progressive enhancement only; the page reads fine with JS off. Stores
// nothing and talks to no server.
(function () {
  "use strict";
  var DAY = 86400000;

  function at(el, attr) {
    var v = el && el.getAttribute(attr);
    if (!v) return null;
    var t = new Date(v).getTime();
    return isNaN(t) ? null : t;
  }

  function tag(text, cls) {
    var t = document.createElement("span");
    t.className = "tag " + cls;
    t.textContent = text;
    return t;
  }

  // Key dates: each <li> carries data-start (and data-end for a span). A
  // point event is past once it starts; a span is past once it ends.
  function markDates(now) {
    var list = document.getElementById("dates-list");
    if (!list) return;
    var items = list.querySelectorAll("li[data-start]");
    for (var i = 0; i < items.length; i++) {
      var li = items[i];
      var start = at(li, "data-start");
      if (start === null) continue;
      var end = at(li, "data-end");
      var state = (end !== null ? now >= end : now >= start) ? "past"
        : (end !== null && now >= start) ? "now" : "ahead";
      if (li.getAttribute("data-state") === state) continue;
      li.setAttribute("data-state", state);
      var old = li.querySelector(".tag");
      if (old) old.parentNode.removeChild(old);
      li.classList.remove("past", "now");
      if (state !== "ahead") li.classList.add(state);
      var d = li.querySelector(".d");
      if (state === "now" && d) d.appendChild(tag("happening now", "tag-now"));
    }
  }

  var local = document.getElementById("launch-local");
  var count = document.getElementById("countdown");
  var next = document.getElementById("next-up");
  var launch = at(local, "data-utc");
  var raids = at(next, "data-utc");

  if (local && launch !== null) {
    try {
      var fmt = new Intl.DateTimeFormat(undefined, {
        weekday: "long", month: "long", day: "numeric",
        hour: "numeric", minute: "2-digit", timeZoneName: "short"
      });
      local.textContent = "Your time: " + fmt.format(launch);
      local.hidden = false;
    } catch (e) { /* old browser: the PST line stands on its own */ }
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  // Four fixed cells (days / hours / min / sec), built once and updated in
  // place each second so the layout never reflows.
  var cells = [];
  if (count && launch !== null) {
    ["days", "hours", "min", "sec"].forEach(function (label) {
      var u = document.createElement("span"); u.className = "u";
      var n = document.createElement("span"); n.className = "n";
      var l = document.createElement("span"); l.className = "l"; l.textContent = label;
      u.appendChild(n); u.appendChild(l); count.appendChild(u);
      cells.push(n);
    });
  }

  // Raid night has a date but no announced hour, so count whole days only.
  function showNext(now) {
    if (!next || raids === null) return;
    var days = Math.ceil((raids - now) / DAY);
    next.textContent = days > 1 ? "Raids open December 9, in " + days + " days."
      : days === 1 ? "Raids open tomorrow, December 9."
      : "Raids are open.";
    next.hidden = false;
  }

  var live = false;
  function tick() {
    var now = Date.now();
    markDates(now);
    if (!count || launch === null) return;
    var ms = launch - now;
    if (ms <= 0) {
      if (!live) {
        count.textContent = "";
        count.appendChild(tag("It's live. Log in.", "done"));
        count.hidden = false;
        live = true;
      }
      showNext(now);
      // Day-level changes only from here, so a minute is plenty.
      setTimeout(tick, 60000);
      return;
    }
    var s = Math.floor(ms / 1000);
    var d = Math.floor(s / 86400); s -= d * 86400;
    var h = Math.floor(s / 3600); s -= h * 3600;
    var m = Math.floor(s / 60); s -= m * 60;
    cells[0].textContent = String(d);
    cells[1].textContent = pad(h);
    cells[2].textContent = pad(m);
    cells[3].textContent = pad(s);
    count.hidden = false;
    setTimeout(tick, 1000);
  }
  tick();
})();
