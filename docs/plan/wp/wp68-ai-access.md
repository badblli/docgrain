# wp68-ai-access — any AI model can read a company's approved collections

- Özet: Yayınlanan koleksiyonları herhangi bir OpenAI uyumlu modele araç (function calling) ve MCP sunucusu olarak sun; model yalnızca kaynaklı bilgiyle cevaplasın, bilmediğinde "bilmiyorum" desin.
- Model: derin
- Engine: codex
- Phase: D5
- Branch: `codex/wp68-ai-access` (base: `origin/dev`)
- Depends on: wp43/wp52 publications (merged)
- Role: implementer

## Goal

Docgrain is the trusted feed, not the chatbot (ROADMAP decisions 3–5, 12). A company plugs its own model
into the approved data: the model gets tools, calls them, and every answer can cite a source.

## Tasks

1. Tool specs (OpenAI function-calling JSON) generated per workspace from the accepted schema:
   `list_collections()`, `search_records(collection, query, filters?)`, `get_record(collection, id)`,
   `get_context(collection)`; each result carries `sources` (document name, locator, quote) and the
   publication mode. Default mode `approved`; `preview` only when the caller asks and the result says so.
   Endpoint: `GET /v1/workspaces/{ws}/ai/tools` (specs) and `POST /v1/workspaces/{ws}/ai/call`
   (`{name, arguments}` → result), read-only, using the existing records repository.
2. MCP server (`packages/access` or `apps/mcp`): the same four tools over MCP stdio, configured with the
   API URL and workspace; document how to add it to Claude Desktop / any MCP client.
3. A tiny reference loop `docs/examples/ask.py`: any OpenAI-compatible endpoint (base URL, model, key from
   env) answers a question with the tools; the system prompt forbids answers without a tool source and
   requires citations; unanswerable → says so. No model call in tests (fake client).
4. Search: deterministic text match over published JSON (names, field values, i18n), ranked; no
   embeddings (ROADMAP decision 2).
5. Tests: specs reflect a discovered schema (clinic `services`, hotel `rooms`); call results carry
   sources; approved mode hides unapproved values; unknown tool/collection errors are clean.

## Acceptance criteria

- [ ] `.venv/Scripts/python -m pytest -q tests/unit` and `ruff check apps packages tests` pass.
- [ ] README section "Use with your AI" (short) and `docs/examples/ask.py` documented.
- [ ] Report with example tool specs and one example call/response (synthetic data).
