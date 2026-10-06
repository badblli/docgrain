# Collection discovery and records

For workspace schemas, start with [collection discovery](#workspace-collection-discovery-wp51).
The commands below retain the earlier hospitality example pipeline.

This opt-in package extracts one record per real thing from a document's compact
`context_projection`. It does not modify the API, worker, or published knowledge.
Install the local domain package and this package to get `docgrain-records`:

```sh
python -m pip install -e packages/domain -e packages/records
docgrain-records extract --document doc_example --api http://localhost:8000 --dry-run
docgrain-records extract --document doc_example --api http://localhost:8000 --lang en \
  --base-url https://model.example/v1 --model configured-model \
  --api-key-env MODEL_API_KEY --out data/records/doc_example
```

No model request occurs without an explicitly supplied endpoint, model and key.
Dry-run reads the API but prints only the aggregate prompt size and planned request
count, including the JSON schemas (excluding retries);
the token count is an estimate, not provider tokenization. Unknown document language
uses `und`; the prompt asks the model to identify source languages without translating.
Published `context.md` is preferred; on 404, the package computes the same deterministic
projection from the pinned canonical snapshot. Other API failures stop extraction.

Successful `extract` writes `records.json`, the exact `context.md` used for the
request, and `source.json` from the same canonical snapshot. `source.json` pins
`document_id`, `workspace_id`, `knowledge_revision_id`, `source_version_id`,
the source file's `content_sha256`, and extraction `lang`. Missing or inconsistent
source pins stop extraction before a model request. Dry-run creates no files.

Extraction processes heading/block ranges targeting 8,000 characters (usually
6,000–10,000). Original `§N` keys and the corresponding canonical object mappings
stay intact. Oversized blocks continue under their original key; long table
continuations retain their source column headers. Plain contexts split at line/word
boundaries. Each section gets a general pass plus separate Policy, ServicePrice,
Activity and Facility passes that explicitly enumerate every stated list/table item.
Focused passes use a schema restricted to their collection. Every quotation is
verified against the **section and original full cited block** before the existing same-document
type/name collapse combines results, translations, Evidence and conflicts.

At most three requests run concurrently by default. Use `--concurrency 1` through
`4`, `--section-chars 8000` (allowed 1,000–10,000), and `--retries 3` to control
latency/cost; `--no-focused-passes` disables the four extra passes. HTTP 429/5xx and
transport failures use bounded retries; unsupported structured output falls back
to the same schema in the prompt. No option enables a model without explicit
configuration. Smaller sections and focused passes increase the request count;
inspect `--dry-run` before re-extracting a large source set.

`source.json.usage` records provider `prompt_tokens`, `completion_tokens` and
`total_tokens` per physical request, including retries, schema fallbacks and failed
responses, plus their aggregate totals. Calls carry section, collection (`null`
for the general pass), attempt number and HTTP status. Missing provider usage is
`null` per call and counted by `missing_usage_calls`; totals include only reported
tokens and are incomplete when that counter is nonzero. When prompt/completion
counts exist without a total, their sum supplies the total. Credentials, model
response bodies and source quotations never appear in usage or failure metadata.

Failed passes appear in `records.json.failures` with section number, source keys,
collection and a sanitized reason. Other passes' verified records are still saved,
even when every pass fails. The CLI exits `1` and warns that extraction is incomplete;
inspect failures and re-run before reviewing or merging the output. A successful
empty list means no verified records were returned, not proof of source completeness.
`context.md` always saves the entire original pinned context for downstream checks.

`records.json` contains `domain`, `schema_version`, `document_id`, `lang`, `records`,
`rejected` and `failures`. Old artifacts without failures/usage remain readable.
`hospitality_schema()` exports its Pydantic-backed JSON Schema.
Supported record types are Property, RoomType, Outlet, Activity, Facility, Policy,
Contact and ServicePrice. Every fact (including names) has `value`, `lang`, and a
nonempty list of `{document_id, locator, quote}`. IDs, types and `review_state`
are structural metadata; records stay `proposed`, or `needs_review` when repeated
entries in one document disagree. No value is semantically accepted.

Model proposals use a typed list of language alternatives for each field; absent
fields use `[]`. The schema rejects extra fields and invalid value types. For each
field, verified English wins regardless of proposal order. All verified non-English
alternatives are retained under `i18n[lang][field]`, with their own evidence. Without
English, the caller's language wins (otherwise the first verified alternative);
this non-English primary is also retained in i18n. A second alternative in the same
language is rejected rather than silently overwriting the first. Multi-document
identity reconciliation and conflict review use the offline merger described below.
Within one document, repeated type plus normalized primary name becomes one
record before writing `records.json`. Equal facts union their Evidence; missing
facts and translations are retained. Different values in the same language are
preserved in the record's `conflicts[field]` with Evidence and mark the record
`needs_review`. The wp42 merge exposes them as separate field candidates.

Every quote must match after NFKC and whitespace normalization, case-sensitively.
In compact projections, locators must resolve to a block (`§2`, `§2 p.3`, `[§2 p.3]`, or its
canonical object ID from the footer) and the quote must occur in that block's body.
DOCX headings use short paragraph or table positions; the complete XML path stays
in the source-key footer. Older projections with bracketed XML paths also verify.
For caller-supplied plain context without compact markers, verification checks the
whole context; the locator is descriptive only. Any invalid evidence drops the entire
language alternative and is listed in `rejected`. If no verified name remains, the
anonymous record is omitted. Quotes are not proof that a value correctly interprets
them; semantic accuracy still requires review and golden-data evaluation.

Endpoints without structured-output support may fall back to the schema in the
system prompt. Local schema and quote validation always apply. Source text is placed
in a separate untrusted user payload and never becomes system instructions.

## Offline workspace merge and field history (WP42)

Run the synthetic example after installing the package, or set
`PYTHONPATH=packages/records;packages/domain` on Windows (use `:` on POSIX):

```sh
python -m docgrain_records.merge_example
python -m docgrain_records.merge_example --store ./merge-example.json
```

The example merges EN/TR sources into one stable record, changes only capacity in
the English source's next version, distinguishes the name's Evidence-only update,
and reopens the store to query the old revision. It makes no API/model requests.
Without `--store` it uses a temporary directory; a supplied path retains history.
Treat store files as private runtime artifacts: they contain source quotations.

`MergeDocument` pins one `document_id` to `source_version_id`,
`knowledge_revision_id` and the corresponding `context`, inside a `workspace_id`.
The caller must supply the actual pinned context; the offline merge cannot check
an external source registry. Wrap each wp41 `Record` in `SourceRecord` with a
caller-owned, durable `source_identity` and optional workspace/type-scoped `aliases`.
For example, wrap verified extraction output as follows:

```python
from docgrain_records import JsonMergeStore, MergeDocument, SourceRecord

document = MergeDocument(
    workspace_id="workspace-example", document_id=extraction.document_id,
    source_version_id="source-example-v1", knowledge_revision_id="knowledge-example-k1",
    context=pinned_context,
    records=[SourceRecord(source_identity=durable_identity[record.id], record=record)
             for record in extraction.records],
)
store = JsonMergeStore("./private-runtime/merge.json", document.workspace_id)
revision = store.merge("merge-example-1", [document])
old_revision = store.get_revision("merge-example-1")
```

wp41 IDs encode extraction order. **Do not copy them into `source_identity`** or
derive it from an editable name. Obtain a durable identity from the source system
or a caller-maintained assignment. An explicit shared alias links translations
with different names. No translation, fuzzy name match or model call is used to
invent identity. Without that link, different-language names remain unmatched.
Source identities are exact and document/type-scoped; aliases are exact and
workspace/type-scoped. Names provide only a weak key: type, actual language, and
NFKC/whitespace-normalized, case-folded name. A whole weak component is left separate
when it would connect multiple established IDs or multiple distinct items from one
document. `match_issues` records these ambiguities. Explicit links between already
distinct stored IDs fail; deliberate reassignment/consolidation needs a later
identity-review policy. WP44 adds explicit reviewed alias decisions for consolidation;
there is still no automatic consolidation of existing IDs.

Identity mappings retain historical names, aliases and deleted IDs, so edits,
translations with explicit identity, restart, reordered input and reappearance
retain IDs. The first allocation is deterministic for the same complete input;
subsequent allocation uses the stored mapping. Keep this store between revisions.
Each call supplies the **complete active document set**, including unchanged
documents; omission removes their contributions. Identical repeated documents are
deduplicated, while multiple different snapshots of one document are rejected.
The JSON file atomically persists identity mappings and immutable merge revisions.
An exclusive writer lock prevents concurrent writes; after a crashed writer, only
remove its `.lock` once you have established the writer has stopped. This is a
local store, not a replacement for the application's transactional database.
Revision IDs also bind a digest of the complete input and explicit decisions.
Repeating the same request returns that saved revision even after later identity
history changes; changing an existing revision's input fails without overwriting it.

Every incoming Evidence is checked again using wp41's NFKC/whitespace and block
locator rules. Any invalid citation rejects the merge without changing the store.
Each resulting citation includes its source version and knowledge revision.
Equal JSON values in the same language coalesce with a deduplicated Evidence union;
different values remain separate `FactCandidate`s. Lists retain order, and values
are not semantically normalized or interpreted. EN wins per field (`en` before
English regions); missing EN uses the lexically first actual available language.
Every non-English candidate, including fallback values, appears in `i18n` with
Evidence. Same-language disagreements appear in `conflicts`; no arbitrary winner
is exposed by `primary` when the primary language has an unresolved conflict.

`primary` is a display proposal, **never an export approval**. Nonconflicting facts
start `proposed`; conflicting facts start `needs_review`. To accept/reject, pass
explicit `ReviewDecision`s to a new merge revision, naming the record, field,
candidate ID, reviewer and reason. Decisions are stored in the revision. At most
one candidate per language may be accepted; other candidates remain visible until
explicitly reviewed. Exporters use `field.accepted()` for primary values or
`field.accepted(lang)` for a translation, and skip `None`. For example:

```python
from docgrain_records import ReviewDecision

record = revision.records[0]
candidate = record.fields["name"].primary
decision = ReviewDecision(
    record_id=record.id, field="name", candidate_id=candidate.id, action="accepted",
    reviewer="reviewer-example", reason="Checked the cited source",
)
reviewed = store.merge("merge-example-reviewed", [document], [decision])
approved_name = reviewed.records[0].fields["name"].accepted()
```

Decisions are never carried automatically. Candidate IDs bind the fact and complete
versioned Evidence set; changed sources require fresh review, even for equal facts.
`compare_revisions(before, after)` compares stable record IDs and fields, returning
record additions/deletions plus field `added`/`removed`/`changed` entries. Independent
flags distinguish primary `value_changed`, `i18n_changed`, `evidence_changed`,
`conflicts_changed`, and `review_changed`; `evidence_only` excludes all fact,
translation, conflict and review changes. Old/new field snapshots are included.
Updating a whole source version changes citation pins on its unchanged fields;
these are Evidence-only changes, not extra fact changes. The old revision remains
queryable and caller mutation cannot alter saved history.

## Cross-document match proposals (WP44)

```sh
docgrain-records match --records ./private-runtime/records --out ./private-runtime/matches
# Review match_proposals.json, then:
docgrain-records merge --records ./private-runtime/records \
  --matches ./private-runtime/matches/match_proposals.json \
  --out ./private-runtime/merged
```

`match` recursively loads per-document `records.json` files. It has no API calls
and does not construct a model client unless all three model options are explicit:
`--base-url`, `--model`, `--api-key-env`. The optional compatible client uses the
existing retry/fallback policy and a separate schema containing only a
`same / different / unsure` answer. Names, facts and quotations remain untrusted
user data; system instructions never include source text. Model answers remain
proposals, including `same`. Numeric conflicts cannot be overridden by a model.

Before scoring, same-type cross-document pairs are blocked by shared distinguishing
name tokens, identical normalized names (including i18n names), agreeing numeric
signatures, or equal contact values. Generic type words and position alone do not
admit candidates. Only retained pairs are recorded in
`match_proposals.json` with snapshot-bound source references, score, signals,
`decision` and `review_state: proposed`. Scores are heuristic support, not
probabilities. Signals compare m², capacity, times, price amounts and other numeric
signatures, names/tokens after case folding, diacritic removal and Cyrillic
transliteration, and weak ordinal alignment when type counts agree. Ordinal
alignment alone cannot link records. No translated-name dictionary or embeddings
are used. Two independent numeric agreements can suggest translated names;
matching distinguishing names/tokens can provide additional support. Inconsistent
numbers or categories suggest `different`. Close competing pairs and inconsistent
transitive components remain `unsure`; no component may contain two records from
one document. Same-name collisions are inspectable during matching and rejected
at the merge boundary; current extraction coalesces them before matching.

`match_summary.json` lists every suggested group and every unmatched record with
its source name, reference and flags. Its per-type counts are **projected counts
if the same proposals are approved**, not proof of review or a merge result.
Both artifacts contain source data and must stay outside Git.

`candidate_counts` reports possible, scored and pruned pairs per collection;
`review_counts` and `review_proposal_ids` list accepted and pending reviews.
To enable the lead's deterministic identity rules explicitly:

```sh
docgrain-records match --records data/records --out data/matches --auto-accept strong
docgrain-records merge --records data/records \
  --matches data/matches/match_proposals.json --out data/merged --auto-accept strong
```

`rule:identical-name` accepts identical NFKC/whitespace-normalized, case-folded,
transliterated primary names of one type. Different field values remain visible
conflicts. `rule:name-and-numbers` requires distinguishing name token Jaccard
similarity of at least 0.75 and agreeing numeric signatures, with no numeric,
category or source conflicts. Identity collisions, competing names and inconsistent
components remain pending. Numeric-only matches and optional model answers stay
proposals; an `unsure` model answer does not grant acceptance. Saved signals are
recomputed from input records before automatic acceptance. Rule reviews include
reviewer/reason and approve identity only; field acceptance remains separate.

To withdraw an accepted link, change its review state to `rejected` with reviewer
and reason and merge a new revision. If accepted paths still connect its endpoints,
withdraw those paths too. Historical revisions stay immutable. One detached source
partition retains the established ID; other partitions receive stable new IDs.
Repeating the request preserves those IDs; reacceptance uses explicit ID decisions.
`merge` saves its effective `match_proposals.json` and `merge_summary.json`, including
actual per-collection record counts, alongside its collection arrays.

To explicitly approve a `same` proposal, set `review_state` to `accepted` and add
nonempty `reviewer` and `reason` strings. A rejected review also requires these
strings. An `unsure` or `different` suggestion cannot be accepted as an alias.
The reviewer can explicitly change the decision after examining its evidence;
this is a review action, never a model/default behavior. Stale snapshot references,
duplicate proposal IDs, accepted many-to-one components and conflicting transitive
links fail without changing the merge store. Every unaccepted pair vetoes
wp42's weak normalized-name matching. Withdrawn links also split historical identity
anchors in the new revision; previous revisions remain queryable.

`merge` keeps wp42's original quote verification: beside **each** `records.json`
it requires the actual pinned `context.md` and a `source.json` sidecar:

```json
{
  "document_id": "doc-example",
  "workspace_id": "workspace-example",
  "knowledge_revision_id": "knowledge-example-k1",
  "source_version_id": "source-example-v1",
  "content_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "lang": "en"
}
```

`extract` produces these three files together. `merge` derives the workspace
from the pins; optional `--workspace` checks it explicitly. All input documents
must belong to that workspace. The source hash is retained in the merge revision.
The adapter never manufactures a context from quotation lists. Missing or
mismatched pins/context, incorrect quotations or duplicate type/name source
identities stop the merge. The CLI's source identity policy is record type plus
NFKC/whitespace-normalized, case-folded primary name, scoped within the document.
A renamed source record therefore requires a newly reviewed link; wp42's lower
level API still accepts durable caller-owned identities.

Only accepted pairs become shared aliases. `aliases.json` records those pair
reviews and the resulting source-to-alias assignments. When an accepted component
connects previously distinct IDs, the adapter emits explicit `AliasDecision`s,
retains the lexically first ID, retires the others in the identity map and records
the decision in the new revision. Old revisions and field decisions remain
unchanged. There is no implicit field acceptance.

`merge_state.json` retains identity mappings/history; `merge_revision.json` stores
the current source-pinned result. Each type also gets a JSON array (`room_type.json`,
`outlet.json`, and the other hospitality types, including empty arrays). Records
use wp42's `fields` envelope with EN-first `primary`, evidenced `i18n`, visible
same-language `conflicts`, candidates and review states. These are review artifacts,
not published accepted data. Repeating an unchanged request returns its immutable
revision; use `--revision` to supply an explicit revision ID or let the CLI derive
one from the full input. Retain the output store between runs and keep all outputs
private.

## Offline end-to-end measurement (WP47)

`docs/examples/score_record_merge.py` uses the read-only WP45 `record_golden`
scorer on saved extraction and merge artifacts. Add the evaluation package
containing that module to `PYTHONPATH`; no model, API or network request occurs.

```sh
python docs/examples/score_record_merge.py --records data/records \
  --merged data/merged/merge_revision.json \
  --manifest /private/golden/manifest.frozen.v2.json \
  --golden /private/golden/fields.jsonl --questions /private/golden/questions.jsonl \
  --out data/measurement
```

It verifies the frozen source hashes and key coverage, then writes per-document,
aggregate extraction, merged primary and merged source-language reports. A source
without annotated fields has no accuracy denominator. Golden files are never
written; before/after key hashes and input receipts are saved. Output directories
must be new to preserve earlier measurements. The sibling `merge_state.json` pins
the measured export and supplies actual source identity mappings (`--state` can
specify another path).

Merged views replicate a canonical record for each contributing document because
WP45's key is document-scoped. Primary views use actual EN-first display values;
source-language views use existing candidates in the document's declared language,
falling back to the display primary if that language is missing. No translations
are generated. Multiple unresolved candidates in the selected language leave the
primary absent and preserve conflict candidates. Source identities supply names
only for WP45's identity alignment; they never fill an omitted display value.
Version pins are retained in the measured merge artifact; the scorer's strict
three-field Evidence shape receives the document, locator and quote only.

Monolingual non-English goldens can flag a correct English display value as a
language/value mismatch. Both views are reported so that limitation stays visible.
Neither score measures distinct canonical entities or certifies unannotated extra
fields. Inspect `report.json` for omissions, wrong values, conflicts and alignment
ambiguities. The helper's successful exit means measurement completed; its
`d4_target.measurement_met` remains false when quality misses the target.
## Workspace collection discovery (WP51)

`discover` derives a workspace schema from normalized source structures for any kind
of company. No industry schema is loaded by this path. Tables with repeated rows,
similar list items, repeated headings/field blocks, and recurring units, times and
prices become deterministic signals. Counts cover all supplied documents; up to six
quoted samples per pattern are sent to the model. This is schema discovery, not a
complete record extraction pass.

With no model flags it scans sources locally, writes `discovery.signals.json` and
an empty `schema.proposed.json`, and makes **no model call**. With an explicitly
configured OpenAI-compatible endpoint it proposes collections and fields, merges
identical keys across the workspace, and verifies each example value's quotes in
the cited source blocks using the existing extractor's NFKC/whitespace/locator
rules. Unsupported fields disappear; rejection reasons remain in `rejected`.
Conflicting field types or units retain `alternatives` and `needs_review`.

Run discovery on every document of a workspace through the live API (paginated
document list, filtered by workspace; every input must have a normalized revision):

```powershell
$env:PYTHONPATH = 'packages/records;packages/domain'
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m docgrain_records discover `
  --workspace <workspace-id> --api http://localhost:8000 `
  --base-url <openai-compatible-base-url> --model <model-name> `
  --api-key-env DOCGRAIN_DISCOVERY_API_KEY --out data/discovery/<workspace-id>
```

Set `DOCGRAIN_DISCOVERY_API_KEY` securely before running; the command never prints
credentials or source samples. Alternatively, replace `--api` with `--sources
<normalized-context-directory>` containing one `source.json` and `context.md` per
document (existing extraction bundles work; `records.json` is not needed). Pins must
belong to the requested workspace and only one revision per document is allowed.
`--dry-run` reports request size and signal count without a model call or output
writes, even if model flags are supplied. `--max-prompt-chars` defaults to 120000;
oversized requests fail before contacting the model, without silently omitting
documents. It can be raised explicitly for a suitable model.

`schema.proposed.json` uses English snake_case collection and field keys. Collection
keys must have a plural-shaped final word (including common irregular plurals).
Actual English meaning and semantic identity require review; syntax cannot prove
either. `label_i18n` is an array of `{lang, value}` entries, allowing any locale and
requiring an English label. Labels may be translated; factual example values retain
the source language. Every collection and field has its own `review_state`.
Example values have `{key, value, lang, evidence}`. Supported types are `string`,
`integer`, `number`, `boolean`, and `string_list`; units are optional (`null`).

Review the proposed keys, labels, definitions and examples, set retained collections
and fields to `accepted`, and set unwanted entries to `rejected`. Resolve type/unit
conflicts by selecting a definition, removing `alternatives`, and correcting or
removing incompatible examples. Keep the top-level state `proposed` and version
`null`, then publish the reviewed schema locally:

```powershell
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m docgrain_records accept-schema `
  --proposal data/discovery/<workspace-id>/schema.proposed.json `
  --out data/discovery/<workspace-id>
```

Acceptance rechecks typed examples and quotes against preserved source contexts
under `schema.sources/`, including a context SHA-256 alongside source-version and
knowledge-revision pins. All retained fields require supporting examples; pending
reviews and unresolved alternatives block publication. The command creates
`schema.v1.json`, `schema.v2.json`, etc., exclusively, without modifying older
versions. Rediscovery includes the latest accepted definitions in the prompt so
equivalent structures can reuse stable keys; definition changes remain reviewable.
Keep source contexts beside the schema artifacts and outside version control.
Quote presence proves source location, not that an example's interpretation is
correct; reviewers must check meaning before accepting.

`WorkspaceSchema` and `collection_record_schema(accepted_schema, collection_key)`
are the industry-independent runtime contract. Record JSON Schema is generated
from reviewed workspace fields, with typed, language-tagged, evidenced values.
Hospitality is one synthetic fixture (`tests/fixtures/collections/hospitality.*`),
alongside clinic and gym tests, and never supplies the discovery/runtime default.
The existing fixed hospitality `extract`/`match`/`merge` commands and Python models
remain available for compatibility with earlier work packages; their artifacts do
not define a workspace schema and are not inputs to the generic runtime contract.
