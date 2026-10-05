# Hospitality records

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
Dry-run reads the API but prints only the prompt size, including the JSON schema;
the token count is an estimate, not provider tokenization. Unknown document language
uses `und`; the prompt asks the model to identify source languages without translating.
Published `context.md` is preferred; on 404, the package computes the same deterministic
projection from the pinned canonical snapshot. Other API failures stop extraction.

`records.json` contains `domain`, `schema_version`, `document_id`, `lang`, `records`,
and `rejected`. `hospitality_schema()` exports its Pydantic-backed JSON Schema.
Supported record types are Property, RoomType, Outlet, Activity, Facility, Policy,
Contact and ServicePrice. Every fact (including names) has `value`, `lang`, and a
nonempty list of `{document_id, locator, quote}`. IDs, types and `review_state`
are structural metadata; records stay `proposed`, not semantically accepted.

Model proposals use a typed list of language alternatives for each field; absent
fields use `[]`. The schema rejects extra fields and invalid value types. For each
field, verified English wins regardless of proposal order. All verified non-English
alternatives are retained under `i18n[lang][field]`, with their own evidence. Without
English, the caller's language wins (otherwise the first verified alternative);
this non-English primary is also retained in i18n. A second alternative in the same
language is rejected rather than silently overwriting the first. Multi-document
identity reconciliation and conflict review belong to later work packages.

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
