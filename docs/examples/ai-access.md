# Use with your AI

Docgrain supplies a trusted feed; your assistant supplies the model. No AI endpoint
calls a model, downloads documents, extracts facts or regenerates a publication.
Configure the API's `RECORDS_PUBLICATION_ROOT` and publish a reviewed revision as
described in [records-read.md](records-read.md). Auth and shared/object storage remain
outside this local publication adapter's scope.

## REST tools

`GET /v1/workspaces/{workspace}/ai/tools` returns `{workspace_id, revision_id,
mode: "approved", tools}`. Pass `tools` directly to an OpenAI-compatible Chat
Completions endpoint with function-calling support. There are exactly five functions:

| Tool | Required arguments | Result payload |
| --- | --- | --- |
| `list_collections` | none | `collections`: keys, field contracts, published record counts |
| `search_records` | `collection`, `query` | ranked `records` matches, each with `record`, `score` and `sources` |
| `get_record` | `collection`, `id` | `record`, including field evidence under `_meta` |
| `get_context` | `collection` | precomputed Markdown `context` |
| `list_collection` | `collection` (optional `fields`) | every record as `records[]`: `record` (id, `name`, requested fields, their translations) and its `sources` ids; `sources` holds only the evidence of the returned fields |

Every tool accepts optional `mode` (`approved` by default; explicit `preview`).
Every result includes `workspace_id`, `revision_id`, `mode` and deduplicated `sources`.
Sources carry a stable `src_…` citation id, document name, locator, quote and existing
document/source-version/knowledge-revision pins. Legacy pins without a document name
use the document id as `document_name`; no filename is guessed. User corrections
keep `kind: "user_edit"`, timestamp and note with null document name/locator/quote;
the reference loop cannot cite them as document evidence.

`POST /v1/workspaces/{workspace}/ai/call` takes `{name, arguments}` and returns the
result. Both endpoints accept `?revision_id=<published-revision>`. Without it they
resolve the newest publication once per request. Pin the revision returned by specs
for all calls in one conversation; the bundled API client does this automatically.
An explicit old revision remains readable after new publications.

Collection enums and per-collection exact filter contracts come from the accepted
schema snapshot of that publication. Clinic `services` and hotel `rooms` therefore
receive different schemas. Legacy hospitality packs use their existing runtime
contract through the same path. Source examples and collection descriptions are
never promoted to tool instructions.

Search uses case-folded, diacritic-insensitive substrings (including Turkish dotted
and dotless i) across plain field values, arrays, numbers and `i18n` values. All query
terms must match somewhere in a record. Name/translated-name matches receive extra
weight; ties sort by stable record id. `filters` is an optional object whose keys
and types must match that collection's fields; all filters require exact equality
with the primary published value. An empty query lists filtered records in id order.
Provenance, document quotes and unapproved values are excluded from approved search.
There are no embeddings, fuzzy semantic matches or model calls.

Unknown workspace/revision/collection/record gives 404; staged unpublished revision
409; unknown tool or invalid arguments 422; corrupt/unavailable artifacts 503. Empty
collections/searches succeed with empty records and sources. The POST only reads;
it does not accept values or change review state. Sources from hidden proposals,
conflicts and rejected candidates never appear in approved tool responses.

## Synthetic example

Abbreviated specs for a workspace whose reviewed collection is `rooms` (the real
responses also include the fixed source/citation policy and optional `mode`):

```json
[
  {"type":"function","function":{"name":"list_collections","parameters":{"type":"object","properties":{},"additionalProperties":false}}},
  {"type":"function","function":{"name":"search_records","parameters":{"type":"object","properties":{"collection":{"type":"string","enum":["rooms"]},"query":{"type":"string"},"filters":{"type":"object","properties":{"name":{"type":"string"},"capacity":{"type":"integer"}},"additionalProperties":false}},"required":["collection","query"],"additionalProperties":false}}},
  {"type":"function","function":{"name":"get_record","parameters":{"type":"object","properties":{"collection":{"type":"string","enum":["rooms"]},"id":{"type":"string"}},"required":["collection","id"],"additionalProperties":false}}},
  {"type":"function","function":{"name":"get_context","parameters":{"type":"object","properties":{"collection":{"type":"string","enum":["rooms"]}},"required":["collection"],"additionalProperties":false}}}
]
```

Request (all values below are synthetic):

```http
POST /v1/workspaces/workspace-example/ai/call?revision_id=r1
Content-Type: application/json

{"name":"get_record","arguments":{"collection":"rooms","id":"rec-room"}}
```

Response excerpt; full responses preserve `i18n`, `_meta` and all visible field evidence
as well. Search metadata wraps each record so company fields named `score` or
`sources` remain intact:

```json
{
  "workspace_id": "workspace-example",
  "revision_id": "r1",
  "mode": "approved",
  "collection": "rooms",
  "record": {"id": "rec-room", "name": "Garden room", "capacity": 2},
  "sources": [{
    "id": "src_example",
    "document_id": "doc-example",
    "document_name": "rooms.txt",
    "source_version_id": "s1",
    "knowledge_revision_id": "k1",
    "locator": "§1 p.1",
    "quote": "2"
  }]
}
```

Citation ids in real responses are deterministic hashes of source metadata, rather
than the illustrative `src_example` above. A consuming assistant can say:
`Oda iki kişiliktir [src_example].` and show `rooms.txt`, `§1 p.1`, quote `2`.
Unapproved views or conflicting prices must not be inferred from this result.

## Reference loop: ask.py

Install the access adapter (or run the example directly from the checkout with the
API's existing `httpx` dependency):

```powershell
python -m pip install -e packages/access
$env:DOCGRAIN_API_URL = 'http://127.0.0.1:8000'
$env:DOCGRAIN_WORKSPACE = 'workspace-synthetic'
python docs/examples/ask.py 'Odada kaç kişi kalabilir?'  # model off; no requests
```

Configure `AI_BASE_URL` (compatible base URL, usually ending `/v1`), `AI_MODEL` and
`AI_API_KEY` in your environment or secret manager. Do not put the key in Git or a
command-line argument. Then explicitly enable the model:

```powershell
python docs/examples/ask.py 'Odada kaç kişi kalabilir?' --enable-model
python docs/examples/ask.py 'Taslakta oda manzarası ne görünüyor?' --enable-model --preview
```

Optional `--api-url`, `--workspace` and `--revision` override the matching
`DOCGRAIN_API_URL`, `DOCGRAIN_WORKSPACE`, `DOCGRAIN_REVISION` environment variables.
The model must support Chat Completions `tools` and `tool_calls`. The loop is bounded
to eight model turns, handles multiple tool calls per turn, returns tool errors to
the model, and blocks model-requested preview unless the caller used `--preview`.
The system prompt requires a tool source for every fact, citations and abstention;
all returned document text remains untrusted data. Output includes document names,
locators and quotes for the cited ids. No source, missing citation, invented source
id, or exhausted loop returns `Bilmiyorum.` Preview output carries a visible label.

The mechanical check verifies that citation ids exist in tool sources; it does not
prove that every generated sentence follows from its citation. That semantic
responsibility remains with the consuming model. Fake-client tests verify the
protocol and abstention gates; they are not a real-model accuracy evaluation.

## MCP stdio: Claude Desktop or another client

Install `packages/access` in the Python environment used by your MCP client.
Start `docgrain-mcp --api-url http://127.0.0.1:8000 --workspace workspace-synthetic`
or `python -m docgrain_access.mcp` with the same flags. Environment configuration
uses `DOCGRAIN_API_URL`, `DOCGRAIN_WORKSPACE` and optional `DOCGRAIN_REVISION`.
The MCP process only calls the configured Docgrain API after a tools request;
it has no model configuration or model calls.

In Claude Desktop's MCP configuration (`claude_desktop_config.json`), or the
equivalent local-server configuration of another stdio MCP client:

```json
{
  "mcpServers": {
    "docgrain": {
      "command": "C:/path/to/python-environment/Scripts/python.exe",
      "args": ["-m", "docgrain_access.mcp"],
      "env": {
        "DOCGRAIN_API_URL": "http://127.0.0.1:8000",
        "DOCGRAIN_WORKSPACE": "workspace-synthetic"
      }
    }
  }
}
```

Use an absolute Python executable path and restart the client after saving its
configuration. On Linux/macOS, use the environment's `bin/python`. If running from
an uninstalled checkout, add `PYTHONPATH: "C:/path/to/docgrain/packages/access"`
under `env`. Use the same host-accessible API URL and workspace as REST.

The adapter implements `initialize`, `notifications/initialized`, `ping`,
`tools/list`, and `tools/call`, exposing the same four API tools. It negotiates
`2025-06-18`, with `2025-03-26` and `2024-11-05` text-only compatibility. Newer clients
must accept one of those versions. Results include text JSON, plus
`structuredContent` for `2025-06-18`; tool failures use `isError`. Each UTF-8 JSON-RPC
message occupies one line; stdout contains only protocol messages. EOF shuts the
process down. No resources, prompts, sampling or Streamable HTTP are advertised.
Protocol references: [stdio transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports),
[lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle),
[tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).

The client pins the first specs revision for the process lifetime. Restart the MCP
process to pick up a newly published schema; configure `DOCGRAIN_REVISION` to keep
using a specific old publication. Preview is available only as an explicit tool
argument and retains `mode: "preview"`; assistant behavior is governed by its host.

## Offline verification

```powershell
$python = 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python'
& $python -m pytest -q tests/unit/test_ai_access.py tests/unit/test_ai_clients.py
& $python -m ruff check apps packages tests docs/examples
```

Tests publish synthetic reviewed records and discover accepted clinic/hotel schemas,
check hidden facts/quotes, source provenance, exact filters and deterministic
ranking, fake compatible model messages, explicit opt-in/preview, revision pins and
MCP newline/lifecycle/error behavior. No real model or source document is used.
