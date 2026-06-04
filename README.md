# Get a Job

A World of Warcraft guild portal under [LLMATIONS](https://github.com/LLMATIONS) → Swag County. Small tools for our Burning Crusade guild, built for the love of the grind.

Lives at <https://getajob.swagcounty.com>.

## What's in here

- `index.html` — the portal hub. **Generated** from `hub/shell.html` + `hub/tiles/*.html` by `hub/build_hub.py`; never hand-edit it (CI blocks drift). See `hub/README.md`.
- `hub/` — the hub source: the page shell, one fragment per tile, and the generator.
- `tbc/` — the TBC dungeon-rep leveling guide. `build_tbc_guide.py` is the source of truth; it renders `tbc/index.html`. Edit the generator, never the HTML.
- `guild-names/` — submit and vote on guild-name ideas, up/down, Reddit-style. Static page + a loopback `/api/*` backend (`server/`).
- `apply/` — the raid-application form. Static page that posts to the same loopback `/api/*` backend.
- `rules/` — the guild rules (static page).
- `server/` — the backend for the vote and apply form (FastAPI + SQLite, loopback-only). See `server/README.md`.
- `assets/` — branding, favicons, social card.
- `privacy.html` — what each tool stores and what leaves your browser.

## The leveling guide

`tbc/build_tbc_guide.py` carries the whole route — factions, dungeons, keys, rep sources, quests — as structured Python and renders one themed, self-contained page. Every in-game reference links to Wowhead (TBC Classic) with hover tooltips, and the route is checkable with your progress saved in the browser (no account, nothing leaves your device). Rebuild with:

```sh
cd tbc && python3 build_tbc_guide.py
```

## Contributing

Solo-built for now, but the door's open. Open an issue for a narrow fix, or a PR against `main` — the PR template covers what a reviewer needs.

## License

[AGPL-3.0](LICENSE). Workshop default across LLMATIONS — keeps SaaS re-skins of the public projects honest.
