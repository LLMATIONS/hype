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
| `hub/tiles/30-rules.html` | Guild Rules tile | rules lane |
| `hub/tiles/40-about.html` | About Us tile | about lane |
| `index.html` | build artifact, served as-is by Caddy | nobody hand-edits |

Tiles render in filename sort order — the `NN-` prefix sets position on the page.

## Editing

- Branding / copy / footer ........ edit `hub/shell.html`
- Add a tile ...................... add `hub/tiles/NN-name.html`
- Flip your tool Soon → Live ...... edit ONLY your `hub/tiles/NN-*.html`

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
