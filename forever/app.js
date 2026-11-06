// Forever sea chart: keep the key-dates list current (past entries dim, the
// running one gets a "happening now" tag) and count whole days to raid night.
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

  var next = document.getElementById("next-up");
  var raids = at(next, "data-utc");

  // Raid night has a date but no announced hour, so count whole days only.
  function showNext(now) {
    if (!next || raids === null) return;
    var days = Math.ceil((raids - now) / DAY);
    next.textContent = days > 1 ? "That's " + days + " days out."
      : days === 1 ? "That's tomorrow."
      : "The raids are open. Muster at the docks.";
    next.hidden = false;
  }

  function tick() {
    var now = Date.now();
    markDates(now);
    showNext(now);
    // Day-level changes only, so a minute is plenty.
    setTimeout(tick, 60000);
  }
  tick();
})();
