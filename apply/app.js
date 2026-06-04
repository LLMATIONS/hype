/* Apply to Raid — front-end logic.
 *
 * Lives in its own file (not an inline <script>) so the page can ship a strict
 * Content-Security-Policy with no 'unsafe-inline' for scripts. The public form
 * just collects fields and POSTs them; the server stores the application and
 * fans it out to Discord + email. The owner-only admin review list (?admin)
 * renders every field with textContent / safe nodes, never innerHTML, so a
 * submitted application can never become markup. */
(function () {
  "use strict";

  var CAPS = { character: 40, discord: 64, wow_class: 32, experience: 1500, why: 1500, logs: 300 };

  // --- tiny dom + fetch helpers --------------------------------------------
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }

  async function api(path, opts) {
    opts = opts || {};
    var res = await fetch(path, {
      method: opts.method || "GET",
      headers: opts.body ? { "Content-Type": "application/json" } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin"
    });
    var data = null;
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) {
      var msg = (data && data.error) || "Something went sideways (" + res.status + "). Try again.";
      var err = new Error(msg); err.status = res.status; err.data = data; throw err;
    }
    return data;
  }

  // --- cloudflare turnstile (bot gate on submit) ---------------------------
  // Rendered only if the backend reports a sitekey, so the page works before
  // the keys are configured.
  var tsWidget = null;
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src; s.async = true; s.defer = true;
      s.onload = resolve; s.onerror = function () { reject(new Error("script load failed")); };
      document.head.appendChild(s);
    });
  }
  async function setupTurnstile() {
    var cfg;
    try { cfg = await api("/api/config"); } catch (e) { return; }
    if (!cfg || !cfg.turnstile_sitekey) return;
    try {
      await loadScript("https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit");
    } catch (e) { return; }
    var box = $("#cf-widget");
    if (!box || !window.turnstile) return;
    box.hidden = false;
    tsWidget = window.turnstile.render(box, { sitekey: cfg.turnstile_sitekey });
  }
  function turnstileToken() {
    return (window.turnstile && tsWidget !== null) ? window.turnstile.getResponse(tsWidget) : null;
  }
  function turnstileReset() {
    if (window.turnstile && tsWidget !== null) { try { window.turnstile.reset(tsWidget); } catch (e) {} }
  }

  // --- character counters ---------------------------------------------------
  function wireCounter(input, counterId, max) {
    var c = $("#" + counterId);
    if (!c) return;
    function upd() { c.textContent = input.value.length + " / " + max; }
    input.addEventListener("input", upd); upd();
  }

  // --- the application form -------------------------------------------------
  var form = $("#apply");
  var btn = $("#apply-btn");
  var statusEl = $("#form-status");
  var doneEl = $("#done");

  var fields = {
    character: $("#character"), discord: $("#discord"), wow_class: $("#wow_class"),
    experience: $("#experience"), why: $("#why"), logs: $("#logs")
  };
  var ackConsumables = $("#ack_consumables");
  var ackFriend = $("#ack_friend");

  wireCounter(fields.character, "character-count", CAPS.character);
  wireCounter(fields.experience, "experience-count", CAPS.experience);
  wireCounter(fields.why, "why-count", CAPS.why);

  function setStatus(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  function val(name) { return (fields[name].value || "").trim(); }

  // Mirror the server's required checks so we fail fast and point at the field.
  function firstProblem() {
    if (!val("character")) return [fields.character, "Your character name's required."];
    if (!val("discord")) return [fields.discord, "Your Discord username's required."];
    if (!val("wow_class")) return [fields.wow_class, "Your class is required."];
    if (!val("experience")) return [fields.experience, "Tell us a bit about your raiding experience."];
    if (!val("why")) return [fields.why, "Tell us why you want to join."];
    var logs = val("logs");
    if (logs && !/^https?:\/\//i.test(logs)) return [fields.logs, "That logs link needs to start with http:// or https://."];
    if (!ackConsumables.checked) return [ackConsumables, "Please confirm the consumables and gear requirement."];
    if (!ackFriend.checked) return [ackFriend, "Please confirm you'll reach out on Discord."];
    return null;
  }

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var problem = firstProblem();
    if (problem) { setStatus(problem[1], "err"); problem[0].focus(); return; }

    btn.disabled = true;
    setStatus("Sending…");
    try {
      await api("/api/apply", {
        method: "POST",
        body: {
          character: val("character"),
          discord: val("discord"),
          wow_class: val("wow_class"),
          experience: val("experience"),
          why: val("why"),
          logs: val("logs") || null,
          ack_consumables: ackConsumables.checked,
          ack_friend: ackFriend.checked,
          token: turnstileToken()
        }
      });
      form.hidden = true;
      setStatus("");
      doneEl.hidden = false;
      doneEl.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (e) {
      setStatus(e.message, "err");
    } finally {
      turnstileReset();   // tokens are single-use
      btn.disabled = false;
    }
  });

  var againBtn = $("#apply-again");
  if (againBtn) {
    againBtn.addEventListener("click", function () {
      form.reset();
      wireCounter(fields.character, "character-count", CAPS.character);
      wireCounter(fields.experience, "experience-count", CAPS.experience);
      wireCounter(fields.why, "why-count", CAPS.why);
      doneEl.hidden = true;
      form.hidden = false;
      turnstileReset();
      fields.character.focus();
    });
  }

  // --- admin review (owner-only) -------------------------------------------
  // Same bearer token as the guild-name vote (server holds it; set via
  // configure-admin.sh). Unlock at /apply/?admin, paste the token; it's kept in
  // localStorage and sent as X-Admin-Token. The server does the real
  // authorization — the UI just reveals the applications list once it checks out.
  var ADMIN_KEY = "guildApply.adminToken.v1";
  var adminToken = null, adminOn = false;
  var adminSection = $("#admin-apps");
  var appsList = $("#apps");
  var appsCount = $("#apps-count");

  function adminFetch(path, opts) {
    opts = opts || {};
    return fetch(path, {
      method: opts.method || "GET",
      headers: { "X-Admin-Token": adminToken },
      credentials: "same-origin"
    });
  }

  async function adminPing(tok) {
    try {
      var r = await fetch("/api/admin/ping", { headers: { "X-Admin-Token": tok }, credentials: "same-origin" });
      return r.ok;
    } catch (e) { return false; }
  }

  async function initAdmin() {
    var url = new URL(location.href);
    var asking = url.searchParams.has("admin");
    var tok = null;
    try { tok = localStorage.getItem(ADMIN_KEY); } catch (e) {}
    if (asking && !tok) { tok = window.prompt("Admin token:"); }
    if (tok && await adminPing(tok)) {
      adminToken = tok; adminOn = true;
      try { localStorage.setItem(ADMIN_KEY, tok); } catch (e) {}
      showAdminBar();
      adminSection.hidden = false;
      await loadApps();
    } else if (tok) {
      try { localStorage.removeItem(ADMIN_KEY); } catch (e) {}
      if (asking) setStatus("Admin token not accepted.", "err");
    }
    if (asking) { url.searchParams.delete("admin"); history.replaceState({}, "", url.toString()); }
  }

  function showAdminBar() {
    if ($("#admin-bar")) return;
    var bar = el("div", "admin-bar"); bar.id = "admin-bar";
    var span = el("span"); span.textContent = "Admin mode — reviewing applications.";
    var lock = el("button", "admin-lock"); lock.type = "button"; lock.textContent = "Exit admin";
    lock.addEventListener("click", function () {
      try { localStorage.removeItem(ADMIN_KEY); } catch (e) {}
      location.reload();
    });
    bar.appendChild(span); bar.appendChild(lock);
    var main = document.querySelector("main");
    main.insertBefore(bar, main.querySelector("header").nextSibling);
  }

  function fmtWhen(iso) {
    try {
      return new Date(iso).toLocaleString("en-US", {
        timeZone: "America/Los_Angeles",
        month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit"
      }) + " PT";
    } catch (e) { return iso; }
  }

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

    var del = el("button", "app-del");
    del.type = "button"; del.textContent = "✕";
    del.title = "Delete (admin)";
    del.setAttribute("aria-label", "Delete application from " + a.character);
    del.addEventListener("click", function () { deleteApp(a.id, a.character); });
    li.appendChild(del);
    return li;
  }

  function renderApps(apps) {
    appsList.textContent = "";
    if (!apps.length) {
      var p = el("p", "apps-empty");
      p.textContent = "No applications yet.";
      appsList.appendChild(p);
    } else {
      apps.forEach(function (a) { appsList.appendChild(appNode(a)); });
    }
    appsCount.textContent = apps.length
      ? apps.length + (apps.length === 1 ? " application" : " applications")
      : "";
  }

  async function loadApps() {
    try {
      var r = await adminFetch("/api/applications");
      if (!r.ok) throw new Error("Couldn't load applications (" + r.status + ").");
      var data = await r.json();
      renderApps(data.applications || []);
    } catch (e) {
      appsList.textContent = "";
      var p = el("p", "apps-empty");
      p.textContent = e.message;
      appsList.appendChild(p);
    }
  }

  async function deleteApp(id, who) {
    if (!adminOn) return;
    if (!window.confirm("Delete the application from " + who + "?")) return;
    try {
      var r = await adminFetch("/api/applications/" + encodeURIComponent(id), { method: "DELETE" });
      if (!r.ok) throw new Error("Delete failed (" + r.status + ").");
      await loadApps();
    } catch (e) { window.alert(e.message); }
  }

  // --- boot ----------------------------------------------------------------
  setupTurnstile();
  initAdmin();
})();
