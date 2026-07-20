# PoE2 Build Ledger — mobile web app

A standalone, installable PWA that wraps this repo's analysis code (EHP,
passive tree, ladder comparison) behind a `poe.ninja` profile URL import.
Paste a profile URL, get the build breakdown, and optionally ask a Claude-
powered Companion tab questions about it.

## Layout

- `public/` — static frontend (`index.html`, PWA manifest, service worker,
  icons). Import a profile URL, see defenses/passive tree/ladder/gear tabs,
  a Companion chat tab, and export/import/refresh a JSON snapshot.
- `api/analyze.py` — FastAPI serverless function with two endpoints:
  - `POST /api/analyze` — fetches and analyzes a character.
  - `POST /api/chat` — the Companion tab's backend. Sends the current
    snapshot plus the user's message to the Claude API (`anthropic` SDK)
    and returns the reply. **Requires an `ANTHROPIC_API_KEY` environment
    variable** on the Vercel project (Project Settings → Environment
    Variables) — without it, the endpoint returns a 503 explaining what's
    missing rather than crashing. Optional `CLAUDE_CHAT_MODEL` env var
    overrides the model (defaults to `claude-sonnet-5`). Usage is billed
    to whatever Anthropic account owns that API key.
  - `GET /api/health` — health check.
- `api/_vendor/src/` — a lean vendored copy of the subset of `src/` this
  endpoint needs (`config.py`, `api/*`, `calculator/ehp_calculator.py`,
  `calculator/defense_calculator.py`, `parsers/passive_tree_resolver.py`,
  `pob/importer.py`). Vendored instead of importing `src` directly because
  `src/calculator/__init__.py` and `src/parsers/__init__.py` pull in
  unrelated heavy dependencies (Timeless Jewel seed calculator, DAT64
  parser) not needed here. `config.py` additionally carries a read-only-
  filesystem fallback for `CACHE_DIR`/`LOGS_DIR` (mirrored in the real
  `src/config.py` in this same commit) since serverless deploys ship the
  repo read-only outside `/tmp`.
- `vercel.json` — classic Vercel config: `@vercel/python` for the API
  function, `@vercel/static` for the frontend.

The passive-tree data file (`data/psg_passive_nodes.json`, ~2MB) is not
bundled — `api/analyze.py` fetches it once from this repo's GitHub raw
content on cold start and caches it in `/tmp`.

## Deploying

From the repo root:

```bash
cd mobile-app
vercel --prod
```

Or import this repo directly in the Vercel dashboard (New Project → Import
Git Repository) and set the project's root directory to `mobile-app/`.
