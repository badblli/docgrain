# ADR 0023 — Local CPU visual proposals and preserved uncertainty

- Date: 2026-10-03
- Status: experimental local runtime implemented; automatic semantic acceptance remains open.
- Extends ADR 0020–0022. Normalization remains local; embedding follows N5.

## Decision

Run a separate, optional llama.cpp image model on CPU. The browser explicitly requests one source-bound proposal. It cannot write canonical data, advance a head or approve a document. A reviewer may adopt a description into a draft, compare it with the source, preview its changes and publish an immutable manual revision through the existing review contract.

The current experimental candidate is **Qwen3.5-2B-Q4_K_M**, profile `qwen35-2b-cpu-1`. The smaller 0.8B candidate misclassified a resort photograph as a plan and invented details; it was rejected. The 2B candidate improved broad photograph/plan recognition but still invented a kitchen/bed details in a family plan and repeated nonexistent image text. It is **not accepted for automatic normalization**, exact geometry, object counts or OCR. `visible_text` must be empty; literal text belongs to the separate pinned OCR/source review path. English descriptions may occur despite the Turkish preference.

This decision creates a usable review aid, not proof that every PDF, Office file or image can be fully understood. Original sources, native tables/formulas, evidence and unresolved semantics remain available.

## Runtime identity and bounds

The packaged `apps/api/docgrain_api/profiles/local-vision-cpu-1.json` pins repository revision, model/projector sizes and SHA-256 values, llama.cpp **b11371** Windows CPU archive and its SHA-256, four threads, context 4096, image budget 1024 and output 384 tokens. Setup downloads explicitly; inference never downloads. Startup verifies weights, archive and extracted executables/DLLs against the archive.

CPU flags disable GPU layers and projector offload; one inference slot, no thinking, temperature zero, seed 42. These options do not establish factual correctness or bitwise reproducibility across hardware. Input bounds: PNG/JPEG only, 4 MB, 20 million pixels; response 64 KiB, 120 second transport timeout. Busy requests return 429. A browser cancellation discards its response but may leave CPU inference running until completion; subsequent requests can remain busy.

The Windows helper starts a hidden process on port 11435 with a private key in ignored files. Binding to `0.0.0.0` allows Docker-to-host access; it is authenticated, not an anonymous public endpoint. The API only permits local hostnames on that port and refuses redirects. A matching model alias is a readiness check; verified owned startup establishes the configured binaries, not a cryptographic remote attestation. Public exposure, multiple API workers, Linux service packaging and production identity/resource limits require separate deployment work.

## Proposal API

| Endpoint | Contract |
| --- | --- |
| `GET /v1/knowledge/revisions/{revision}/visuals/local/config` | Revision-scoped enablement/readiness/profile. Default disabled; demo disabled. |
| `POST /v1/knowledge/revisions/{revision}/visuals/local/proposals` | Exact snapshot SHA and evidence-backed node required. Pinned original and artifact storage versions, scope, byte size and SHA are verified before inference. |

The result includes proposed status, revision/source/snapshot/node/artifact/evidence bindings, binary/model/projector/prompt SHA values, classification, description, empty visible text, uncertainties and elapsed time. Invalid/truncated output fails; no cloud fallback or partial accepted data. Proposals are not persisted by the server; export JSON when retaining a proposal is needed.

## Additive manual review contract

- Section headings join source-bound text editing. Node identity, child order, source, evidence and artifact arrays remain unchanged.
- Description changes can include `visual_uncertainties` and supplemental `source_evidence_ids`. Supplemental evidence must belong to the same canonical source and is included in preview, manual provenance and audit. It lets an image's room label cite its actual PDF section heading instead of guessing room type from pixels.
- Known uncertainties survive description edits and model adoption. The reviewer can explicitly edit notes after checking the source; clearing notes is itself previewed/audited. Whole-document approval and coverage never advance automatically.
- Metadata carries per-node notes. AI JSON/Markdown quality gaps and Gemini context retain them. A description alone cannot hide unreadable dimensions or inaccessible geometry.
- Linked entities/relations/records block affected fields. Demonstrably separate source evidence allows independent edits while all linked data remains byte-for-byte unchanged. Unknown dependencies fail closed; same PDF page stays conservative. This is not comprehensive dependent-fact reconciliation.
- Empty additive fields are omitted from identity normalization. A regression proves pre-extension legacy preview/revision/snapshot identity unchanged.
- Every Gemini-returned image requires its own valid node/evidence citation. Source-ID validity still does not prove the model's claims are true.

## Measured evidence and current limits

On the local 16 GB machine, CPU-only exploratory 2B calls took 4.3–16.5 seconds for four small existing images; some outputs were rejected. The final bounded endpoint/browser photograph call took **10.075 seconds**, returned empty visible text and uncertainty, and did not write a revision. Observed process working set was approximately 2.8 GB; this is not whole-stack peak, throughput, p95 or a certified deployment minimum. Model plus projector download is approximately 2.06 GB, excluding runtime/cache/other models.

Codex separately compared original asset bytes and PDF pages, then published two explicitly audited manual revisions: Corendon 13 descriptions (room images cite source headings) and Dobedan 10 logo descriptions plus three known table corrections. Five images retain six uncertainty notes, including four plans. These are selected source checks by Codex, not user approval, model acceptance or held-out corpus acceptance. Original revisions and packages are preserved.

Four Gemini **consumer** calls without attached image selections returned the exact expected Family photograph, standard-room plan and pool photograph; the absent exact bed width abstained without citations/images. Gemini received normalized canonical context, not original image bytes in these calls. This small test does not close automated normalization, cross-document retrieval or N5. No embedding/index/ingestion was run.

## Primary references

- [Publisher model card and license](https://huggingface.co/Qwen/Qwen3.5-2B).
- [Pinned GGUF distributor](https://huggingface.co/bartowski/Qwen_Qwen3.5-2B-GGUF).
- [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md).

Next gates: automatic model quality against source goldens/held-out scans, native chart/diagram meaning, comprehensive dependent-fact review and N5 source↔UI↔package acceptance. Embedding remains last.
