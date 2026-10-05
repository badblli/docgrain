# wp14-eval-scoring-fixes — Score answers by meaning, not formatting

- Özet: Puanlayıcının biçim yüzünden doğru cevapları yanlış saymasını düzelt: 24:00=00:00, aralıklardaki boşluklar, yapılandırılmış value nesneleri, çelişki sorularında saat eşleşmesi.
- Model: standart
- Phase: D1
- Branch: `codex/wp14-eval-scoring-fixes` (base: `origin/dev`)
- Depends on: wp12 (merged). Runs in parallel with wp13, which edits `cli.py`/`api.py`; you edit
  `scoring.py`, its tests and the local golden file only.
- Role: implementer

## Evidence (first baseline, local file)

`C:/Users/root/Documents/projects/docgrain/data/eval/baseline-canonical/results.jsonl` +
`data/golden/questions.jsonl`. 9 answers were scored wrong; reading them, at most 2–3 are real
errors. Known false negatives (ids in the local results):

- `q023`, `q070`: `24:00` vs `00:00`, and `09:00 - 24:00` vs `09:00-00:00`.
- `q042`: `24 - 27 m²` vs expected text `24-27 m²` (spaces around `-`/`–`).
- `q002`: `value` was an object `{"total_area": 32000, "unit": "m²"}`.
- `q045`: `value` was `{"opening_time": "23:30", "closing_time": "02:00"}` while `answer` text had the range.
- `q069`, `q070`: conflict answers named both sources and both ranges, but time formatting differed.
- `q057`: `4 ila 12 yaş` vs `4-12 yaş` (Turkish range wording).

## Tasks

1. `scoring.py`:
   - Normalize times: `24:00` ≡ `00:00`; accept `HH.MM`; ranges with any of `-`, `–`, `—`, `ile`,
     `ila`, ` to ` and surrounding spaces.
   - Text/list answers: normalize range separators and spaces around them before containment.
   - Number answers: if `value` is an object, use its single numeric field (or `value`/`amount` key);
     else fall back to numbers in `answer`.
   - Time-range answers: try `value` (string or object with open/close-like keys), then `answer`.
   - Conflict answers: an expected item matches if its normalized value (time-range aware) occurs
     in the answer.
   - Keep `unanswerable` and abstention logic unchanged.
2. Re-score the existing baseline **without calling a model**: add `docgrain-eval rescore <run-dir>
   --questions …` that recomputes `correct` and the summary from stored `results.jsonl` + `parsed`.
   Write to `<run-dir>/rescored/`.
3. Unit tests for every case above (synthetic strings, no customer content).
4. Run the rescore on the baseline and list, per question that is still wrong, why (one line).
   For `q057`/`q064`, if the golden answer is too narrow, add `accept` forms in the **local**
   `data/golden/questions.jsonl` (not in Git) and say so.

## Acceptance criteria

- [ ] New tests pass; existing eval tests pass; Ruff clean (repo venv).
- [ ] Rescore output with the remaining wrong answers explained.
- [ ] No model calls.
