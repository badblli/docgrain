# Docgrain

**Turn messy company documents into versioned, source-linked knowledge your AI, apps and website can trust.**

[![Quality](https://github.com/badblli/docgrain/actions/workflows/quality.yml/badge.svg?branch=dev)](https://github.com/badblli/docgrain/actions/workflows/quality.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB)

[Türkçe](README.tr.md) · [Roadmap](docs/plan/ROADMAP.md) · [Quick start](#quick-start)

> **Pre-alpha, honestly.** Today Docgrain turns PDF, DOCX, XLSX, TXT and PNG/JPEG files into a
> reviewable, source-linked model and publishes it as JSON, Markdown and ZIP. The shared data pool,
> the access API for AI and apps, and file versioning are not built yet. The table below says exactly
> what works. It is early; stars and feedback help shape it.

## Why

- **Company knowledge is trapped in PDF, Excel and Word.** Tables break, scans are images, and the same
  fact lives in three files that disagree.
- **RAG without provenance hallucinates.** If an answer cannot point at a page, cell or box, nobody can
  check it, so nobody should trust it.
- **One-word edits reprocess the whole document.** Updating a price should not mean re-ingesting every
  file and losing the corrections people already made.

## What it does

Four goals. Markers are literal: ✅ works in code today, 🚧 in progress, 🗺 planned.

1. **One model for every format.** ✅ Six formats are normalized into a single canonical model, and
   every fact keeps its evidence (page, cell, box). A person reviews it next to the source; each edit is
   an immutable revision. ✅ Output is published as canonical JSON, Markdown, `ai.json`, chunks and ZIP.
   🚧 Tables flattened by some PDFs are not yet extracted as real tables.
2. **Versions without reprocessing.** 🗺 Upload a new file version and add only what changed as a new
   revision; old revisions stay.
3. **Collections as one shared data pool.** 🗺 Typed lists (rooms, products, services, policies) feed
   AI, mobile apps and websites from the same accepted data.
4. **Model-agnostic, fast answers.** ✅ A compact AI context (`context.md`) is published with every
   revision: one workspace went from ~514k to ~128k characters with no table cell lost. 🗺 Access for any
   OpenAI-compatible model (context packs + function-calling tools); embeddings optional, off the
   critical path.

Docgrain is not a chatbot. It produces packs, APIs and tool specs that your own assistant uses. The
core is domain-neutral; industry schemas live outside it.

## How it works

```text
PDF / DOCX / XLSX / TXT / PNG / JPEG
        │  upload + validate
        ▼
   canonical model  ◄── human review (next to the source, every edit = a new revision)
        │
        ├─► publish: JSON / Markdown / ZIP            ✅ today
        └─► collections → API / AI access             🗺 not yet
```

## Quick start

Needs Docker, or Python 3.12 and Node for the demo.

### Live stack (Docker Compose)

```sh
cp .env.example .env
docker compose up --build
```

| Service | Address |
| --- | --- |
| Web UI | http://localhost:3000 |
| API and OpenAPI | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |

Compose starts the API, worker, web, PostgreSQL, Redis, MinIO and Qdrant. Qdrant is not wired to
any feature yet. `.env` is git-ignored; local passwords are for development only. External vision and
Gemini calls are off by default.

### Demo mode (no infrastructure)

Serves synthetic, read-only data; uploads return `409`; no worker needed.

```powershell
python -m pip install -e 'packages/domain[validation]' -e 'apps/api[dev]'
$env:USE_FIXTURES = "true"
python -m uvicorn docgrain_api.main:app --port 8000
```

In a second terminal:

```sh
cd apps/web
npm ci
npm run dev
```

`GET /healthz` reports the running `mode` (`live` or `demo`).

### Tests

```sh
python -m pip install -e 'packages/domain[validation]' -e 'apps/api[dev]'
python -m pytest -q
ruff check apps packages tests benchmarks docs/examples
cd apps/web && npm ci && npm run build
```

CI also installs `pymupdf>=1.24`; add it if missing. The same three steps run as `make quality`
(`make test`, `make lint`, `make web-build` also work alone). Docling, EasyOCR, PostgreSQL and MinIO
integration tests run inside the worker Docker image.

## Measured, not claimed

Nothing counts as done until it is measured. `docgrain-eval` scores published document content against
golden questions and table facts deterministically: answer accuracy, abstention on unanswerable
questions, and citation hits. Numbers will be published per release. **The first baseline is coming**;
none is published yet, so there are no numbers here.

```sh
pip install -e packages/evaluation
docgrain-eval run --questions <questions.jsonl> --workspace ws_local \
  --api http://localhost:8000 --dry-run
```

A model is called only when you drop `--dry-run` and provide an OpenAI-compatible endpoint and key.
`tables` and `compare` commands exist too. Details: [`docs/plan/eval.md`](docs/plan/eval.md); golden
format: [`docs/plan/golden-format.md`](docs/plan/golden-format.md). Golden data, real documents and
eval output (`data/`) are never committed; this repository is public.

## Built by an AI team

Docgrain is developed by a small team of AI agents with a human product owner. **Claude Code is the
tech lead.** Codex agents named after Pokémon (Charizard, Alakazam, Porygon, Jigglypuff, Bulbasaur)
each take one work package in their own git worktree and branch; **Chatot**, a Claude scribe, writes
docs. Every change is reviewed, re-tested and measured by the lead before it merges. Text that looks
like instructions inside source documents is treated as data, never as a command. Rules:
[`AGENTS.md`](AGENTS.md); work packages: [`docs/plan/wp/`](docs/plan/wp/); tooling:
[`scripts/team/`](scripts/team/).

## Roadmap

Full plan: [`docs/plan/ROADMAP.md`](docs/plan/ROADMAP.md).

- **D1 Measurement:** golden questions and tables, `docgrain-eval` against any OpenAI-compatible model, first baseline.
- **D2 Extraction fixes:** flattened tables become real tables; external images kept as links.
- **D3 File versions:** upload a new version, see a diff, carry accepted edits forward.
- **D4 Collections:** typed records with evidence, multi-document merge with visible conflicts.
- **D5 Access layer:** read-only REST for apps, precomputed AI context, OpenAI tool specs.
- **D6 Change propagation:** an edit republishes only the affected parts, with webhooks.
- **D7 Simple UI:** one primary action per screen, mobile-friendly (in parallel from D3).

Later: embeddings only if measurement shows a need; auth, multi-tenant isolation, queue recovery.

## Contributing

Small, well-tested changes are welcome; see [`CONTRIBUTING.md`](CONTRIBUTING.md). Architecture:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); decisions: [`docs/adr/`](docs/adr/README.md). Security
reports: [`SECURITY.md`](SECURITY.md). Never commit API keys or real customer files.

## License

MIT. See [`LICENSE`](LICENSE).
