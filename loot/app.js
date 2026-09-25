/* Loot Log — front-end logic.
 *
 * External file (not inline) so the page can ship a CSP without 'unsafe-inline'
 * for our own script. It GETs /api/loot (public, read-only) and renders the
 * standings, the "needs gear" view, and a recent-drops feed. All player and
 * item text is set with textContent — never innerHTML — so names from the
 * Gargul log can never become markup. Item links point at Wowhead so the
 * tooltips widget can decorate them. */
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }

  var CLASSES = {
    warrior: 1, paladin: 1, hunter: 1, rogue: 1, priest: 1, shaman: 1,
    mage: 1, warlock: 1, druid: 1, deathknight: 1, monk: 1, demonhunter: 1, evoker: 1
  };
  function classCls(cls) {
    return (cls && CLASSES[cls]) ? "pname cls-" + cls : "pname";
  }

  async function api(path) {
    var res = await fetch(path, { credentials: "same-origin" });
    var data = null;
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) {
      var msg = (data && data.error) || "Couldn't load the loot log (" + res.status + ").";
      var err = new Error(msg); err.status = res.status; throw err;
    }
    return data;
  }

  // --- renderers ------------------------------------------------------------
  function renderSummary(d) {
    var box = $("#summary");
    box.textContent = "";
    var chips = [
      [d.totals.ms, "Main-spec"],
      [d.totals.os, "Off-spec"],
      [d.totals.players, "Raiders"],
      [d.totals.awards, "Total drops"]
    ];
    chips.forEach(function (c) {
      var chip = el("div", "chip");
      var b = el("b"); b.textContent = c[0];
      var s = el("span"); s.textContent = c[1];
      chip.appendChild(b); chip.appendChild(s); box.appendChild(chip);
    });
    box.hidden = false;
  }

  function renderTrials(d) {
    var panel = $("#trials-panel"), wrap = $("#trials");
    if (!d.trials_enabled || !d.trials || !d.trials.length) { panel.hidden = true; return; }
    wrap.textContent = "";
    d.trials.forEach(function (t) {
      var card = el("div", "tcard" + (t.due ? " due" : ""));
      var head = el("div", "thead-row");
      var name = el("div", classCls(t.class)); name.textContent = t.player;
      head.appendChild(name);
      if (t.due) { var b = el("span", "badge-due"); b.textContent = "READY"; head.appendChild(b); }
      // progress pips: one per required lockout, filled up to what they've raided
      var pips = el("div", "pips");
      for (var i = 0; i < t.needed; i++) {
        pips.appendChild(el("span", "pip" + (i < t.lockouts ? " on" : "")));
      }
      var count = el("span", "tmeta");
      count.textContent = t.lockouts + " / " + t.needed + " lockouts";
      pips.appendChild(count);
      var meta = el("div", "tmeta");
      meta.textContent = t.due ? "Ready to evaluate"
        : (t.started ? "Trial since " + t.started : "In trial");
      card.appendChild(head); card.appendChild(pips); card.appendChild(meta);
      wrap.appendChild(card);
    });
    panel.hidden = false;
  }

  function renderHurting(d) {
    var wrap = $("#hurting");
    wrap.textContent = "";
    if (!d.hurting.length) { $("#needs-panel").hidden = true; return; }
    d.hurting.forEach(function (p) {
      var card = el("div", "hcard");
      var name = el("div", classCls(p.class)); name.textContent = p.player;
      var meta = el("div", "pmeta");
      var since = p.days_since_ms == null
        ? "No main-spec yet"
        : (p.days_since_ms === 0 ? "MS today" : p.days_since_ms + "d since MS");
      meta.textContent = p.ms + " MS · " + since;
      card.appendChild(name); card.appendChild(meta); wrap.appendChild(card);
    });
    $("#needs-panel").hidden = false;
  }

  var STANDINGS = [];
  var SORT = { key: "ms", dir: -1 };

  function sortStandings() {
    var k = SORT.key, dir = SORT.dir;
    STANDINGS.sort(function (a, b) {
      var av = a[k], bv = b[k];
      if (k === "player") { av = (av || "").toLowerCase(); bv = (bv || "").toLowerCase(); }
      // days_since_ms: null (no MS ever) sorts as the largest drought
      if (k === "days_since_ms") { if (av == null) av = 1e9; if (bv == null) bv = 1e9; }
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      // stable tiebreak by name
      return a.player.toLowerCase() < b.player.toLowerCase() ? -1 : 1;
    });
  }

  function renderStandings() {
    var body = $("#standings-body");
    body.textContent = "";
    STANDINGS.forEach(function (p) {
      var tr = el("tr");
      var name = el("td"); var sp = el("span", classCls(p.class)); sp.textContent = p.player; name.appendChild(sp);
      var ms = el("td"); ms.textContent = p.ms;
      var os = el("td"); os.className = "dim"; os.textContent = p.os;
      var tot = el("td"); tot.textContent = p.total;
      var last = el("td"); last.className = "dim";
      last.textContent = p.days_since_ms == null ? "—" : (p.days_since_ms === 0 ? "today" : p.days_since_ms + "d");
      var lock = el("td");
      if (p.locked) { var b = el("span", "badge-lock"); b.textContent = p.lockout_ms; lock.appendChild(b); }
      else { lock.textContent = p.lockout_ms || 0; lock.className = "dim"; }
      [name, ms, os, tot, last, lock].forEach(function (c) { tr.appendChild(c); });
      body.appendChild(tr);
    });
  }

  function wireSort() {
    var ths = document.querySelectorAll("th.sortable");
    ths.forEach(function (th) {
      th.addEventListener("click", function () {
        var key = th.getAttribute("data-key");
        if (SORT.key === key) { SORT.dir *= -1; }
        else { SORT.key = key; SORT.dir = (key === "player") ? 1 : -1; }
        ths.forEach(function (o) { o.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", SORT.dir === 1 ? "ascending" : "descending");
        th.querySelector(".arrow").textContent = SORT.dir === 1 ? "▴" : "▾";
        sortStandings(); renderStandings();
      });
    });
  }

  function renderRecent(d) {
    var ul = $("#recent");
    ul.textContent = "";
    if (!d.recent.length) { $("#recent-panel").hidden = true; return; }
    d.recent.forEach(function (r) {
      var li = el("li");
      var tag = el("span", "spec-tag " + (r.off_spec ? "spec-os" : "spec-ms"));
      tag.textContent = r.off_spec ? "OS" : "MS";
      var who = el("span", "who " + (r.class ? "cls-" + r.class : "")); who.textContent = r.player;
      // r.guildie is false only when the roster has synced AND this winner isn't
      // on it — i.e. a PUG. Tag them so the feed stays honest without hiding them.
      if (r.guildie === false) {
        var pug = el("span", "pug-tag"); pug.textContent = "PUG"; who.appendChild(document.createTextNode(" ")); who.appendChild(pug);
      }
      var got = el("span", "dim"); got.textContent = " won ";
      var item;
      if (r.item_id) {
        item = el("a", "wh");
        item.href = "https://www.wowhead.com/forever/item=" + encodeURIComponent(r.item_id);
        item.target = "_blank"; item.rel = "noopener";
        item.textContent = r.item_name || ("item " + r.item_id);
      } else {
        item = el("span"); item.textContent = r.item_name || "an item";
      }
      var meta = el("span", "meta");
      meta.textContent = r.at + (r.awarded_by ? " · " + r.awarded_by : "");
      li.appendChild(tag); li.appendChild(who); li.appendChild(got); li.appendChild(item); li.appendChild(meta);
      ul.appendChild(li);
    });
    $("#recent-panel").hidden = false;
    // let the Wowhead widget decorate the freshly-inserted links
    if (window.$WowheadPower && typeof window.$WowheadPower.refreshLinks === "function") {
      window.$WowheadPower.refreshLinks();
    }
  }

  // --- gear-over-time chart ---------------------------------------------
  // Same-origin inline SVG, no charting library. Stacked bars (MS bottom,
  // OS on top) per raid week, oldest -> newest left to right.
  var SVG_NS = "http://www.w3.org/2000/svg";
  function svgEl(tag, attrs) {
    var e = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) { if (attrs.hasOwnProperty(k)) e.setAttribute(k, attrs[k]); }
    return e;
  }
  function weekLabel(iso) {
    // iso is "YYYY-MM-DD" (UTC reset-week start date) -> "Jun 24"
    var parts = (iso || "").split("-");
    if (parts.length !== 3) return iso || "";
    var d = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  }

  function renderHistory(h) {
    var panel = $("#history-panel"), svg = $("#history-chart");
    svg.textContent = "";
    var weeks = (h && h.weeks) || [];
    if (!weeks.length) { panel.hidden = true; return; }

    var W = 640, H = 220;
    var padL = 28, padR = 10, padT = 10, padB = 28;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var maxTotal = weeks.reduce(function (m, w) { return Math.max(m, w.total); }, 0) || 1;
    var n = weeks.length;
    var slot = plotW / n;
    var barW = Math.max(4, Math.min(28, slot * 0.6));

    // gridlines + y-axis ticks (0, mid, max) for a scale reference
    [0, 0.5, 1].forEach(function (frac) {
      var y = padT + plotH * (1 - frac);
      svg.appendChild(svgEl("line", {
        x1: padL, x2: W - padR, y1: y, y2: y, class: "gridline"
      }));
      var label = svgEl("text", { x: 2, y: y + 3, class: "axis-label" });
      label.textContent = Math.round(maxTotal * frac);
      svg.appendChild(label);
    });

    weeks.forEach(function (w, i) {
      var x = padL + i * slot + (slot - barW) / 2;
      var msH = (w.ms / maxTotal) * plotH;
      var osH = (w.os / maxTotal) * plotH;
      var msY = padT + plotH - msH;
      var osY = msY - osH;
      if (w.ms > 0) {
        var msRect = svgEl("rect", { x: x, y: msY, width: barW, height: Math.max(msH, 0), class: "bar-ms" });
        var msTitle = svgEl("title", {});
        msTitle.textContent = weekLabel(w.week) + ": " + w.ms + " main-spec";
        msRect.appendChild(msTitle);
        svg.appendChild(msRect);
      }
      if (w.os > 0) {
        var osRect = svgEl("rect", { x: x, y: osY, width: barW, height: Math.max(osH, 0), class: "bar-os" });
        var osTitle = svgEl("title", {});
        osTitle.textContent = weekLabel(w.week) + ": " + w.os + " off-spec";
        osRect.appendChild(osTitle);
        svg.appendChild(osRect);
      }
      // sparse x labels so long histories don't collide: first, last, and every
      // Nth week in between
      var stride = Math.max(1, Math.ceil(n / 8));
      if (i === 0 || i === n - 1 || i % stride === 0) {
        var xl = svgEl("text", {
          x: x + barW / 2, y: H - 8, class: "axis-label", "text-anchor": "middle"
        });
        xl.textContent = weekLabel(w.week);
        svg.appendChild(xl);
      }
    });

    panel.hidden = false;
  }

  function renderUpdated(d) {
    var p = $("#updated");
    var bits = [];
    if (d.data_updated) bits.push("Updated " + d.data_updated);
    if (d.lockout_start) bits.push("Lockout since " + d.lockout_start);
    p.textContent = bits.join(" · ");
  }

  async function load() {
    var status = $("#status");
    try {
      var d = await api("/api/loot");
      // Trials are attendance-driven, not loot-driven: render them even before
      // any loot has been logged.
      renderTrials(d);
      var hasTrials = !!(d.trials_enabled && d.trials && d.trials.length);
      if (!d.totals || !d.totals.awards) {
        if (hasTrials) { status.hidden = true; }
        else { status.textContent = "No loot logged yet. Awards show up here after the next raid syncs."; }
        return;
      }
      STANDINGS = d.standings.slice();
      renderSummary(d);
      renderHurting(d);
      sortStandings(); renderStandings();
      $("#standings-panel").hidden = false;
      wireSort();
      renderRecent(d);
      renderUpdated(d);
      status.hidden = true;
      // Best-effort: a history-endpoint hiccup shouldn't take down the rest of
      // the page, which has already rendered successfully above.
      try {
        var h = await api("/api/loot/history");
        renderHistory(h);
      } catch (e) {
        $("#history-panel").hidden = true;
      }
    } catch (e) {
      status.className = "status err";
      status.textContent = e.message || "Couldn't load the loot log. Try again in a bit.";
    }
  }

  load();
})();
