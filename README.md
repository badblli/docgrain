<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="apps/web/public/brand/logo-dark.svg">
    <img src="apps/web/public/brand/logo-light.svg" alt="docgrain" width="260">
  </picture>
</p>

<p align="center">
  <b>Your company's shared memory, with every source attached.</b><br>
  Docgrain turns company documents into versioned, source-linked collections that your AI, apps and
  website can trust. Conflicts are asked, never guessed.
</p>

<p align="center">
  <a href="https://github.com/badblli/docgrain/actions/workflows/quality.yml"><img src="https://github.com/badblli/docgrain/actions/workflows/quality.yml/badge.svg?branch=dev" alt="Quality"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-245d65.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/status-pre--alpha-956316" alt="Status: pre-alpha">
  <img src="https://img.shields.io/badge/python-3.12-245d65" alt="Python 3.12">
</p>

<p align="center"><a href="README.tr.md">Türkçe</a> · <a href="docs/plan/ROADMAP.md">Roadmap</a> · <a href="#quick-start">Quick start</a> · <a href="docs/brand/BRAND.md">Brand</a></p>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/screens/ozet-dark.png">
  <img src="docs/brand/screens/ozet-light.png" alt="Docgrain console: company summary with four measures, a conflict question grouped by source document, and collection cards">
</picture>
<p align="center"><sub>Sample data from the brand kit, not a real company.</sub></p>

> **Pre-alpha, honestly.** Docgrain already ingests a company's folder, discovers its collections,
> extracts source-linked records, asks people about real conflicts and publishes preview and approved
> JSON. File versioning, the AI access layer and auth are not built yet. The list below says exactly
> what works.

## Why

- **Company knowledge is trapped in PDF, Excel and Word.** Tables break, scans are images, and the same
  fact lives in three files that disagree.
- **RAG without provenance hallucinates.** If an answer cannot point at a page, cell or box, nobody can
  check it, so nobody should trust it.
- **One-word edits reprocess the whole document.** Updating a price should not mean re-ingesting every
  file and losing the corrections people already made.

## What it does

Markers are literal: ✅ works in code today, 🚧 in progress, 🗺 planned.

1. **One model for every format.** ✅ PDF, DOCX, XLSX, TXT, PNG and JPEG are normalized into one canonical
   model; every fact keeps its evidence (page, cell, box, line). ✅ A whole company folder is ingested in
   one go into its own workspace, re-runs reuse identical files.
2. **Collections discovered, not hard-coded.** ✅ An OpenAI-compatible model proposes the company's own
   collections (rooms, restaurants, services…) from the normalized content, with quotes verified against
   the source; names are aligned to one vocabulary across companies. ✅ Records are extracted and merged
   across documents and languages (English first, other languages kept as translations).
3. **No guessing.** ✅ Every published field cites its source; fields without evidence are rejected.
   ✅ When documents disagree, Docgrain asks one precise question, options grouped by document
   ("talimatlar.txt says … / factsheet says …"). Recurring schedules are recognised, so two parties that
   swapped Saturdays become one question, not 32 dates. ✅ Each answer publishes a new immutable revision.
4. **Feeds AI and apps.** ✅ Read-only JSON per collection in `preview` and `approved` modes, with ETags,
   plus a compact Markdown context. 🗺 Tool specs for any OpenAI-compatible model; embeddings optional.
5. **Versions without reprocessing.** 🗺 Upload a new file version and carry accepted answers forward.

Docgrain is not a chatbot. It produces packs, APIs and tool specs that your own assistant uses. The
core is domain-neutral; industry schemas live outside it.

## How it works

```text
company folder (PDF / DOCX / XLSX / TXT / PNG / JPEG)
        │  ingest-folder: one workspace per company
        ▼
   canonical model, every fact with evidence
        │  discover collections → extract records → match and merge
        ▼
   merge revision ── questions for real conflicts ◄── people answer (Sorular)
        │                                                │ new immutable revision
        ▼                                                ▼
   publish: preview / approved JSON + context.md  ──►  AI, apps, website
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
tech lead**: it plans work packages, reviews every diff, re-runs the tests and measures on real data
before anything merges. Engineers named after Pokémon (Charizard, Alakazam, Porygon, Jigglypuff,
Bulbasaur) run on Codex or Gemini, each in its own git worktree and branch. **Smeargle**, a Claude
designer, owns the brand and screens ([brand kit](docs/brand/BRAND.md)); **Chatot**, a Claude scribe,
writes docs. The web console is Next.js, Tailwind CSS and shadcn/ui. Text that looks like instructions
inside source documents is treated as data, never as a command. Rules: [`AGENTS.md`](AGENTS.md); work
packages: [`docs/plan/wp/`](docs/plan/wp/); tooling: [`scripts/team/`](scripts/team/).

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
