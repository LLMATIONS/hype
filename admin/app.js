/* hype — admin app.
 *
 * Served only on hype-admin.swagcounty.com, behind Authentik forward-auth on
 * an internal origin that isn't exposed to the public internet. There is NO
 * token here: the reverse proxy verifies
 * the SSO session and injects the admin's identity, and the backend authorizes
 * on that. This script just lists + deletes. Every value from the API is written
 * with textContent / safe nodes (never innerHTML), so a submitted name or
 * application can never become markup. */
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }

  async function api(path, opts) {
    opts = opts || {};
    var res = await fetch(path, {
      method: opts.method || "GET",
      credentials: "same-origin",
      headers: { "Accept": "application/json" }
    });
    var data = null;
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) {
      var msg = (data && data.error) || "Request failed (" + res.status + ").";
      if (res.status === 403) msg = "Not authorized — the Authentik gate isn't passing your identity through.";
      var err = new Error(msg); err.status = res.status; throw err;
    }
    return data;
  }

  var statusEl = $("#status");
  function setStatus(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  // --- who am I -------------------------------------------------------------
  async function showWhoami() {
    try {
      var d = await api("/api/admin/whoami");
      if (d && d.username) {
        var who = $("#whoami");
        who.textContent = "Signed in as ";
        var b = el("b"); b.textContent = d.username; who.appendChild(b);
      }
    } catch (e) { /* the lists will surface any auth problem */ }
  }

  // --- guild names ----------------------------------------------------------
  var ideasEl = $("#ideas");
  var namesCountEl = $("#names-count");
  var namesLoadingEl = $("#names-loading");

  function fmtScore(n) { return (n > 0 ? "+" : "") + n; }
  function scoreClass(n) { return n > 0 ? "score pos" : n < 0 ? "score neg" : "score"; }
  function fmtWhen(iso) {
    try {
      return new Date(iso).toLocaleString("en-US", {
        timeZone: "America/Los_Angeles",
        month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit"
      }) + " PT";
    } catch (e) { return iso; }
  }

  function ideaNode(idea) {
    var li = el("li", "idea");
    li.dataset.id = idea.id;

    var score = el("span", scoreClass(idea.score));
    score.textContent = fmtScore(idea.score);

    var body = el("div", "body");
    var name = el("p", "idea-name"); name.textContent = idea.name; // textContent => XSS-safe
    body.appendChild(name);
    if (idea.why) { var why = el("p", "idea-why"); why.textContent = idea.why; body.appendChild(why); }
    var meta = el("p", "idea-meta");
    meta.textContent = "+" + idea.ups + " / -" + idea.downs + " · " + fmtWhen(idea.created_at);
    body.appendChild(meta);

    var del = el("button", "del");
    del.type = "button"; del.textContent = "✕"; del.title = "Delete name";
    del.setAttribute("aria-label", "Delete " + idea.name);
    del.addEventListener("click", function () { deleteIdea(idea.id, idea.name); });

    li.appendChild(score); li.appendChild(body); li.appendChild(del);
    return li;
  }

  function renderIdeas(ideas) {
    ideasEl.textContent = "";
    if (!ideas.length) {
      var p = el("p", "empty"); p.textContent = "No names pitched yet."; ideasEl.appendChild(p);
    } else {
      ideas.forEach(function (i) { ideasEl.appendChild(ideaNode(i)); });
    }
    namesCountEl.textContent = ideas.length
      ? ideas.length + (ideas.length === 1 ? " name" : " names") : "";
  }

  async function loadIdeas() {
    try {
      var data = await api("/api/ideas");
      renderIdeas(data.ideas || []);
    } catch (e) {
      ideasEl.textContent = "";
      var p = el("p", "empty"); p.textContent = e.message; ideasEl.appendChild(p);
    } finally {
      namesLoadingEl.style.display = "none";
    }
  }

  async function deleteIdea(id, name) {
    if (!window.confirm('Delete "' + name + '"? This removes the name and its votes.')) return;
    try {
      await api("/api/admin/ideas/" + encodeURIComponent(id), { method: "DELETE" });
      setStatus("Deleted “" + name + ".”", "ok");
      await loadIdeas();
    } catch (e) { setStatus(e.message, "err"); }
  }

  // --- applications ---------------------------------------------------------
  var appsEl = $("#apps");
  var appsCountEl = $("#apps-count");
  var appsLoadingEl = $("#apps-loading");

  function badge(channel, st) {
    var b = el("span", "badge " + (st || "off"));
    b.textContent = channel + ": " + (st || "off");
    return b;
  }

  function defRow(dl, term, value, asLink) {
    var dt = el("dt"); dt.textContent = term; dl.appendChild(dt);
    var dd = el("dd");
    if (asLink && /^https?:\/\//i.test(value)) {
      var a = el("a"); a.href = value; a.textContent = value;
      a.target = "_blank"; a.rel = "noopener nofollow noreferrer";
      dd.appendChild(a);
    } else {
      dd.textContent = value;  // textContent => XSS-safe
    }
    dl.appendChild(dd);
  }

  function appNode(a) {
    var li = el("li", "app");
    li.dataset.id = a.id;

    var top = el("div", "app-top");
    var char = el("span", "app-char"); char.textContent = a.character;
    var meta = el("span", "app-meta");
    meta.textContent = a.wow_class + " · " + fmtWhen(a.created_at);
    top.appendChild(char); top.appendChild(meta);
    li.appendChild(top);

    var dl = el("dl");
    defRow(dl, "Discord", a.discord);
    defRow(dl, "Raiding experience", a.experience);
    defRow(dl, "Why join", a.why);
    if (a.logs) defRow(dl, "Logs", a.logs, true);
    li.appendChild(dl);

    var badges = el("div", "app-badges");
    badges.appendChild(badge("discord", a.delivered_discord));
    badges.appendChild(badge("email", a.delivered_email));
    li.appendChild(badges);

    var del = el("button", "del");
    del.type = "button"; del.textContent = "✕"; del.title = "Delete application";
    del.setAttribute("aria-label", "Delete application from " + a.character);
    del.addEventListener("click", function () { deleteApp(a.id, a.character); });
    li.appendChild(del);
    return li;
  }

  function renderApps(apps) {
    appsEl.textContent = "";
    if (!apps.length) {
      var p = el("p", "empty"); p.textContent = "No applications yet."; appsEl.appendChild(p);
    } else {
      apps.forEach(function (a) { appsEl.appendChild(appNode(a)); });
    }
    appsCountEl.textContent = apps.length
      ? apps.length + (apps.length === 1 ? " application" : " applications") : "";
  }

  async function loadApps() {
    try {
      var data = await api("/api/admin/applications");
      renderApps(data.applications || []);
    } catch (e) {
      appsEl.textContent = "";
      var p = el("p", "empty"); p.textContent = e.message; appsEl.appendChild(p);
    } finally {
      appsLoadingEl.style.display = "none";
    }
  }

  async function deleteApp(id, who) {
    if (!window.confirm("Delete the application from " + who + "?")) return;
    try {
      await api("/api/admin/applications/" + encodeURIComponent(id), { method: "DELETE" });
      setStatus("Deleted the application from " + who + ".", "ok");
      await loadApps();
    } catch (e) { setStatus(e.message, "err"); }
  }

  // --- boot -----------------------------------------------------------------
  showWhoami();
  loadIdeas();
  loadApps();
})();
