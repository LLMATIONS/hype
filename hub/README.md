# Hub — the hype.swagcounty.com landing page

`index.html` at the repo root is **generated**. Do not hand-edit it.

The hub is a portal of tiles, and each tile belongs to a different tool lane
(rules, about, and whatever comes next). To keep two lanes from ever
editing the same file, the hub is split into single-owner pieces:

| Path | What | Owner |
|---|---|---|
| `hub/shell.html` | page chrome — head, branding copy, footer | presentation lane |
| `hub/build_hub.py` | the generator | presentation lane |
| `hub/tiles/10-forever.html` | Forever launch prep tile | forever lane |
| `hub/tiles/20-guild-names.html` | Guild Name Vote tile | guild-name-vote lane |
| `hub/tiles/30-rules.html` | Guild Rules tile | rules lane |
| `hub/tiles/40-about.html` | About Us tile | about lane |
| `hub/app.js` | keeps the hub's dates current (served as `/hub/app.js`) | presentation lane |
| `index.html` | build artifact, served as-is by Caddy | nobody hand-edits |

Tiles render in filename sort order — the `NN-` prefix sets position on the page.

## Editing

- Branding / copy / footer ........ edit `hub/shell.html`
- Add a tile ...................... add `hub/tiles/NN-name.html`
- Flip your tool Soon → Live ...... edit ONLY your `hub/tiles/NN-*.html`
  (a not-yet-live tile is `<a class="entry soon">`; drop `soon` to go live)

## Dates that update themselves

`hub/app.js` reads three attributes, so a date on the hub never needs a hand
edit as it passes. Any tile or the shell can use them:

- `data-at="2026-11-04T23:00:00Z"`: an exact instant in UTC. Shows "in 4 days",
  "in 5 hours", "in 40 min", then the `data-done` label once it has passed.
- `data-day="2026-12-09"`: a date with no announced hour, read as a Pacific
  calendar day. Shows "in N days", "tomorrow", "today", then `data-done`.
- `data-flip-at="<UTC instant>" data-after="<text>"`: swaps the element's
  text for `data-after` once the instant passes.

The static text is what JS-off visitors see, so write it to make sense before
the date.

Styling lives in `assets/hype.css`, shared by every public page. Tiles use
`.entry` / `.entry-title` / `.entry-desc` / `.entry-note`; no inline styles.

Then rebuild and commit the result:

```sh
python3 hub/build_hub.py
```

CI (`.github/workflows/hub-build.yml`) runs `python3 hub/build_hub.py --check`
on every PR and fails if `index.html` is out of sync — i.e. someone hand-edited
it or forgot to rebuild.

## The lane rule

A tool lane touches **only** its own tile fragment plus its own subtree
(`about/`, `rules/`, `server/`, …). It never edits `index.html`, `hub/shell.html`,
or another lane's tile. That single-owner split is what makes concurrent work on
the hub safe — no two lanes can land in the same file.
