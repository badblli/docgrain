# ADR 0022 — Canonical Gemini Q&A acceptance probe

- Date: 2026-10-03
- Status: experimental local consumer; source semantic acceptance remains N3/N5.

## Decision

Add a small **Belgeye sor** screen inside the end-user review workspace. The user explicitly selects the canonical revision, asks an independent question, and optionally attaches up to three canonical PNG/JPEG assets. The experiment tests whether normalized text/cells/descriptions and source references are sufficient for correct answers and related image delivery. It is separate from document normalization and does not edit canonical data.

No embedding, vector index, original PDF/Office parsing, provider normalization or automatic model invocation is involved. The client sends an explicit per-question consent. Default server `GEMINI_CHAT_ENABLED=false`; local review Compose enables API chat with the existing Gemini key. Worker remote vision remains disabled with a blank key.

## Contract

- `GET /v1/knowledge/revisions/{revision_id}/chat/config`: safe enabled/model flags, revision scope checked in live mode.
- `POST /v1/knowledge/revisions/{revision_id}/chat`: strict snapshot SHA-256, nonblank question (2,000 chars), actual boolean `allow_remote: true`, unique optional image node IDs (max 3).
- Context contains canonical reading order, exact scalar cells plus display/formula/cache facts, descriptions, per-node/cell evidence and explicit gaps. Limit 100,000 characters; exceeding it fails 413 rather than silently cutting content.
- Only explicitly attached image bytes are read for provider input, with source/document/version scope and pinned size/SHA/version verification. Total 4 MiB max. Original source files are never sent.
- Gemini receives document content as untrusted data, no executable tools, deterministic temperature and structured output schema. One REST call, 45-second timeout, capped response, no redirects/retries. Credentials only in a header and never logged or returned.
- Answer cites node + evidence IDs. Foreign or unbound citations, invalid JSON, uncited non-abstained answers, and foreign/unidentified image references fail 502. Artifact URLs are constructed by the server from canonical references. Missing visual descriptions stay unknown unless the user explicitly attaches that visual to the question.
- Returned citations show actual EvidenceView locators; images load through the existing verified artifact endpoint. Historical revisions remain independently queryable. The response includes revision/model/hash, answer, abstention, citations, images and explicit gap/unreviewed warnings.

## Limits

ID/evidence validation confirms provenance references, not the truth or relevance of every generated claim. A model can still misread a table or pick a poor image; source comparison and held-out answer/image goldens remain necessary. A chat answer or attached-image interpretation is not an accepted visual description or new canonical revision.

Each question is independent; previous turns are browser display only and are not sent as model context. Docgrain does not persist chat history. Production needs authenticated identities, tenancy/rate/cost controls and a larger document context strategy before external deployment. This small acceptance consumer does not turn Docgrain into a chat framework. N3 automated visual semantic gate and N5 remain open; embedding follows N5.

## Provider reference

REST and structured output fields follow Google's primary documentation: [generateContent](https://ai.google.dev/api/generate-content), [structured outputs](https://ai.google.dev/gemini-api/docs/structured-output). The existing configured model is used; no new model/billing account is silently selected.
