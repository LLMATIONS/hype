# hype

A World of Warcraft guild portal under [LLMATIONS](https://github.com/LLMATIONS) → Swag County. Small tools for our guild, built for the love of the grind. Between games right now: we left The Burning Crusade Anniversary and we're waiting on World of Warcraft: Forever.

Lives at <https://hype.swagcounty.com>.

## What's in here

- `index.html`: the portal hub. **Generated** from `hub/shell.html` + `hub/tiles/*.html` by `hub/build_hub.py`; never hand-edit it (CI blocks drift). See `hub/README.md`.
- `hub/`: the hub source: the page shell, one fragment per tile, and the generator.
- `about/`: who we are and where we're headed (static page).
- `forever/`: the WoW: Forever launch prep page. Static, plus a small same-origin `app.js` for the launch countdown in your time zone.
- `apply/`: the raid-application form. **Parked** until Forever recruiting opens: unlinked from the hub and redirected to it. Static page that posts to a loopback `/api/*` backend.
- `loot/`: the loot log and trial tracker. **Parked** the same way; its ingest and sync jobs are stopped and will be pointed at the new realm and guild once we raid again.
- `rules/`: the guild rules (static page).
- `server/`: the backend for the apply form and loot log (FastAPI + SQLite, loopback-only). Also still hosts the retired guild-name vote's endpoints and data, frozen and unlinked. See `server/README.md`.
- `assets/`: branding, favicons, social card.
- `privacy.html`: what each tool stores and what leaves your browser.

## Retired

- The Burning Crusade dungeon-rep leveling guide (`tbc/`) came out with the move off TBC. It lives in git history if anyone wants it back.

## Contributing

Solo-built for now, but the door's open. Open an issue for a narrow fix, or a PR against `main` — the PR template covers what a reviewer needs.

## License

[AGPL-3.0](LICENSE). Workshop default across LLMATIONS — keeps SaaS re-skins of the public projects honest.
