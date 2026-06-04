/* Guild Name Vote — front-end logic.
 *
 * Lives in its own file (not an inline <script>) so the page can ship a strict
 * Content-Security-Policy with no 'unsafe-inline' for scripts. All user content
 * is written with textContent / setAttribute, never innerHTML, so a submitted
 * name can never become markup. */
(function () {
  "use strict";

  var NAME_MAX = 24, WHY_MAX = 200;  // NAME_MAX = WoW's guild-name cap

  // --- anonymous per-browser id (the vote key) -----------------------------
  // Generated once, kept in localStorage. Clearing site data gets you a new
  // identity — the honest limit of one-vote-per-browser without login.
  var ID_KEY = "guildVote.voterId.v1";
  function voterId() {
    var id = null;
    try { id = localStorage.getItem(ID_KEY); } catch (e) {}
    if (!id) {
      id = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : "vid-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
      try { localStorage.setItem(ID_KEY, id); } catch (e) {}
    }
    return id;
  }
  var VID = voterId();

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
  // the keys are configured. Votes are not gated (rate limit + browser id
  // cover those); only submissions carry a token.
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

  // --- rendering -----------------------------------------------------------
  var listEl = $("#ideas");
  var loadingEl = $("#loading");
  var countEl = $("#idea-count");
  var statusEl = $("#form-status");

  function setStatus(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  function scoreClass(n) { return n > 0 ? "score pos" : n < 0 ? "score neg" : "score"; }
  function fmtScore(n) { return (n > 0 ? "+" : "") + n; }
  function cssId(id) { return (window.CSS && CSS.escape) ? CSS.escape(id) : id; }

  function ideaNode(idea) {
    var li = el("li", "idea");
    li.dataset.id = idea.id;

    var votes = el("div", "votes");
    var up = el("button", "vote up");
    up.type = "button"; up.textContent = "▲";
    up.setAttribute("aria-label", "Upvote " + idea.name);
    var score = el("span", scoreClass(idea.score));
    score.textContent = fmtScore(idea.score);
    var down = el("button", "vote down");
    down.type = "button"; down.textContent = "▼";
    down.setAttribute("aria-label", "Downvote " + idea.name);

    up.setAttribute("aria-pressed", idea.your_vote === 1 ? "true" : "false");
    down.setAttribute("aria-pressed", idea.your_vote === -1 ? "true" : "false");
    up.addEventListener("click", function () { castVote(idea.id, 1); });
    down.addEventListener("click", function () { castVote(idea.id, -1); });

    votes.appendChild(up); votes.appendChild(score); votes.appendChild(down);

    var body = el("div", "body");
    var name = el("p", "idea-name"); name.textContent = idea.name; // textContent => XSS-safe
    body.appendChild(name);
    if (idea.why) { var why = el("p", "idea-why"); why.textContent = idea.why; body.appendChild(why); }

    li.appendChild(votes); li.appendChild(body);
    return li;
  }

  function render(ideas) {
    listEl.textContent = "";
    if (!ideas.length) {
      var p = el("p", "empty");
      p.textContent = "No names yet. Pitch the first one — set the tone.";
      listEl.appendChild(p);
    } else {
      ideas.forEach(function (idea) { listEl.appendChild(ideaNode(idea)); });
    }
    countEl.textContent = ideas.length
      ? ideas.length + (ideas.length === 1 ? " idea" : " ideas")
      : "";
  }

  // Update a single card in place after a vote (no reorder — the cards don't
  // jump under your cursor; the list re-sorts on the next load or submit).
  function patchCard(idea) {
    var li = listEl.querySelector('.idea[data-id="' + cssId(idea.id) + '"]');
    if (!li) return;
    var score = $(".score", li);
    score.textContent = fmtScore(idea.score);
    score.className = scoreClass(idea.score);
    $(".vote.up", li).setAttribute("aria-pressed", idea.your_vote === 1 ? "true" : "false");
    $(".vote.down", li).setAttribute("aria-pressed", idea.your_vote === -1 ? "true" : "false");
  }

  function flash(id) {
    var li = listEl.querySelector('.idea[data-id="' + cssId(id) + '"]');
    if (!li) return;
    li.scrollIntoView({ behavior: "smooth", block: "center" });
    li.classList.add("flash");
    setTimeout(function () { li.classList.remove("flash"); }, 1600);
  }

  // --- actions -------------------------------------------------------------
  var voting = {}; // de-dupe rapid clicks per idea

  async function castVote(id, dir) {
    if (voting[id]) return;
    var li = listEl.querySelector('.idea[data-id="' + cssId(id) + '"]');
    var pressed = li && $(".vote." + (dir === 1 ? "up" : "down"), li).getAttribute("aria-pressed") === "true";
    var value = pressed ? 0 : dir; // clicking your active vote clears it
    voting[id] = true;
    try {
      var data = await api("/api/ideas/" + encodeURIComponent(id) + "/vote", {
        method: "POST", body: { voter_id: VID, value: value }
      });
      patchCard(data.idea);
      setStatus("");
    } catch (e) {
      setStatus(e.message, "err");
    } finally {
      voting[id] = false;
    }
  }

  var form = $("#pitch");
  var btn = $("#pitch-btn");
  var nameIn = $("#name");
  var whyIn = $("#why");

  function wireCounter(input, counterId, max) {
    var c = $("#" + counterId);
    function upd() { c.textContent = input.value.length + " / " + max; }
    input.addEventListener("input", upd); upd();
  }
  wireCounter(nameIn, "name-count", NAME_MAX);
  wireCounter(whyIn, "why-count", WHY_MAX);

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var name = nameIn.value.trim();
    if (name.length < 2) { setStatus("Give it a real name first.", "err"); nameIn.focus(); return; }
    btn.disabled = true;
    setStatus("Pitching…");
    try {
      var data = await api("/api/ideas", {
        method: "POST",
        body: { name: name, why: whyIn.value.trim() || null, voter_id: VID, token: turnstileToken() }
      });
      form.reset();
      wireCounter(nameIn, "name-count", NAME_MAX); // reset counters
      wireCounter(whyIn, "why-count", WHY_MAX);
      setStatus("On the ballot. Go rally some votes.", "ok");
      await load();
      flash(data.idea.id);
      nameIn.focus();
    } catch (e) {
      setStatus(e.message, "err");
      if (e.status === 409 && e.data && e.data.existing_id) { flash(e.data.existing_id); }
    } finally {
      turnstileReset();   // tokens are single-use
      btn.disabled = false;
    }
  });

  // --- initial load --------------------------------------------------------
  async function load() {
    try {
      var data = await api("/api/ideas?voter_id=" + encodeURIComponent(VID));
      render(data.ideas || []);
    } catch (e) {
      listEl.textContent = "";
      var p = el("p", "empty");
      p.textContent = "Couldn’t load the ballot. Refresh in a sec.";
      listEl.appendChild(p);
    } finally {
      loadingEl.style.display = "none";
    }
  }

  setupTurnstile();
  load();
})();
