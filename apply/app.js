/* Apply to Raid — front-end logic.
 *
 * Lives in its own file (not an inline <script>) so the page can ship a strict
 * Content-Security-Policy with no 'unsafe-inline' for scripts. The public form
 * just collects fields and POSTs them; the server stores the application and
 * fans it out to Discord + email. Review/moderation lives on the separate,
 * Authentik-gated admin app (getajob-admin.swagcounty.com), not here. */
(function () {
  "use strict";

  var CAPS = { character: 40, discord: 64, wow_class: 32, wow_spec: 20, experience: 1500, why: 1500, logs: 300 };

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
    wow_spec: $("#wow_spec"), experience: $("#experience"), why: $("#why"), logs: $("#logs")
  };
  var ackConsumables = $("#ack_consumables");
  var ackFriend = $("#ack_friend");

  wireCounter(fields.character, "character-count", CAPS.character);
  wireCounter(fields.discord, "discord-count", CAPS.discord);
  wireCounter(fields.wow_spec, "wow_spec-count", CAPS.wow_spec);
  wireCounter(fields.experience, "experience-count", CAPS.experience);
  wireCounter(fields.why, "why-count", CAPS.why);
  wireCounter(fields.logs, "logs-count", CAPS.logs);

  function setStatus(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  function val(name) { return (fields[name].value || "").trim(); }

  // The server stores one class string; "Resto" + "Druid" -> "Resto Druid".
  // Spec is capped at 20 and the longest class is 7 chars, so this always
  // fits the server's 32-char class limit.
  function composedClass() {
    var spec = val("wow_spec");
    return spec ? spec + " " + val("wow_class") : val("wow_class");
  }

  // Mirror the server's required checks so we fail fast and point at the field.
  function firstProblem() {
    if (!val("character")) return [fields.character, "Your character name's required."];
    if (!val("discord")) return [fields.discord, "Your Discord username's required."];
    if (!val("wow_class")) return [fields.wow_class, "Pick your class."];
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
          wow_class: composedClass(),
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
      // Move focus to the confirmation so screen-reader users land on it.
      var doneHeading = doneEl.querySelector("h2");
      if (doneHeading) { doneHeading.setAttribute("tabindex", "-1"); doneHeading.focus({ preventScroll: true }); }
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
      // Counters are wired once at load; reset() doesn't fire 'input', so nudge
      // the existing listeners to refresh the displays instead of re-wiring
      // (re-wiring would stack duplicate listeners on every "submit another").
      Object.keys(fields).forEach(function (k) { fields[k].dispatchEvent(new Event("input")); });
      doneEl.hidden = true;
      form.hidden = false;
      turnstileReset();
      fields.character.focus();
    });
  }

  // --- boot ----------------------------------------------------------------
  setupTurnstile();
})();
