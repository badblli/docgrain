"""Bounded, resumable execution of opt-in pair decisions; no source text in logs."""

import json
import math
import os
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Literal

import httpx
from pydantic import Field, ValidationError

from .match import BATCH_SYSTEM, SYSTEM, PairAnswer, Signal, fingerprint
from .model import ModelResponseError
from .models import StrictModel, Text


@dataclass
class MatchStats:
    total: int = 0
    decided: int = 0
    resumed: int = 0
    model_calls: int = 0  # HTTP attempts, including compatible-format fallback and retries.
    elapsed: float = 0


class MatchBudgetExceeded(ValueError):
    """Incomplete work is checkpointed, never presented as a final match result."""


class ProgressEntry(StrictModel):
    run: Text
    id: Text
    decision: Literal["same", "different", "unsure"]
    score: float = Field(ge=0, le=1)
    signals: list[Signal]
    model: bool


class Journal:
    def __init__(self, path, run):
        self.path = Path(path) if path is not None else None
        self.run = run
        self.saved = {}
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return
        # A killed process may leave a partial final line; discard only that tail.
        with self.path.open("r+b") as stream:
            while line := stream.readline():
                if not line.endswith(b"\n"):
                    stream.truncate(stream.tell() - len(line))
                    break
                try:
                    entry = ProgressEntry.model_validate_json(line)
                except ValidationError as exc:
                    raise ValueError("invalid match progress entry") from exc
                if entry.run == run:
                    self.saved[entry.id] = entry

    def save(self, proposals):
        if self.path is None:
            return
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            for proposal in proposals:
                entry = ProgressEntry(run=self.run, id=proposal.id, decision=proposal.decision,
                                      score=proposal.score, signals=proposal.signals,
                                      model=any(s.kind == "model" for s in proposal.signals))
                stream.write(entry.model_dump_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def open_journal(results, client, strong_names, path):
    if path is None:
        return Journal(None, "memory")
    # Full input fingerprint invalidates decisions when names, fields, schemas or
    # rival records change. Scheduling/budget changes do not invalidate them.
    model_key = ([str(client.client.base_url), client.model] if hasattr(client, "client") else
                 getattr(client, "cache_key", type(client).__module__ + "." + type(client).__qualname__)
                 if client is not None else None)
    run = fingerprint(["matching-v2", strong_names, model_key,
                       [r.model_dump(mode="json") for r in sorted(results, key=lambda r: r.document_id)]])
    return Journal(path, run)


def _batches(jobs, size, chars):
    batch = []
    for job in jobs:
        candidate = [*batch, job]
        # Bound the entire message content, including escaped JSON and the system prompt.
        length = max(len(BATCH_SYSTEM) + len(json.dumps({"untrusted_pairs": candidate}, ensure_ascii=False)),
                     len(SYSTEM) + len(json.dumps({"untrusted_records": job["untrusted_records"]},
                                                 ensure_ascii=False)))
        if batch and (len(candidate) > size or length > chars):
            yield batch
            batch = []
        if not batch:
            length = max(len(BATCH_SYSTEM) + len(json.dumps({"untrusted_pairs": [job]}, ensure_ascii=False)),
                         len(SYSTEM) + len(json.dumps({"untrusted_records": job["untrusted_records"]},
                                                     ensure_ascii=False)))
            if length > chars:
                raise ValueError("one record pair exceeds --batch-chars; increase the prompt limit")
        batch.append(job)
    if batch:
        yield batch


def decide_pairs(proposals, jobs, client, *, journal,
                 concurrency, batch_size, batch_chars, max_minutes, progress, stats, started):
    if not 1 <= concurrency <= 32:
        raise ValueError("match concurrency must be between 1 and 32")
    if batch_size < 1 or batch_chars < 1000:
        raise ValueError("batch size must be positive and batch chars must be at least 1000")
    if max_minutes is not None and (not math.isfinite(max_minutes) or max_minutes <= 0):
        raise ValueError("max minutes must be a finite positive number")
    stats = stats if stats is not None else MatchStats()
    stats.total = len(proposals)
    stats.decided = stats.resumed = stats.model_calls = 0
    deadline = started + max_minutes * 60 if max_minutes is not None else math.inf
    next_progress = started + 20
    lock = Lock()

    def report():
        stats.elapsed = time.monotonic() - started
        if progress is not None:
            progress(stats)

    def usage(_):
        with lock:
            stats.model_calls += 1

    pending, ready = [], []
    lookup = {p.id: p for p in proposals}
    for proposal in proposals:
        if proposal.id in journal.saved:
            stats.resumed += 1
            stats.decided += 1
        elif proposal.id in jobs:
            pending.append(jobs[proposal.id])
        else:
            ready.append(proposal)
            stats.decided += 1
    for offset in range(0, len(ready), 128):
        journal.save(ready[offset:offset + 128])
    report()

    def complete(batch):
        if hasattr(client, "complete_pairs"):
            answers = client.complete_pairs(batch, on_usage=usage)
        else:
            # Compatibility for existing in-process single-pair judges. Network
            # PairClient always implements bounded batching and usage callbacks.
            usage(None)
            raw = client.complete([
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(
                    {"untrusted_records": batch[0]["untrusted_records"]}, ensure_ascii=False)},
            ])
            try:
                answers = {batch[0]["id"]: PairAnswer.model_validate_json(raw).decision}
            except ValidationError as exc:
                raise ModelResponseError("model output is not a valid pair decision") from exc
        if not isinstance(answers, dict) or set(answers) != {p["id"] for p in batch} or any(
            value not in {"same", "different", "unsure"} for value in answers.values()
        ):
            raise ModelResponseError("model output is not a valid pair decision batch")
        return answers

    size = batch_size if hasattr(client, "complete_pairs") else 1
    batches = iter(_batches(pending, size, batch_chars))
    exhausted = False
    failure = None
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        active = {}
        while active or not exhausted:
            while not exhausted and failure is None and len(active) < concurrency and time.monotonic() < deadline:
                try:
                    batch = next(batches)
                except StopIteration:
                    exhausted = True
                    break
                except ValueError as exc:
                    failure = exc
                    break
                active[pool.submit(complete, batch)] = batch
            if not active:
                break
            done, _ = wait(active, timeout=max(0, next_progress - time.monotonic()),
                           return_when=FIRST_COMPLETED)
            for future in done:
                active.pop(future)
                try:
                    answers = future.result()
                except (httpx.HTTPError, ValueError, OSError, RuntimeError) as exc:
                    # Drain already sent requests and persist their successful results
                    # even if a sibling request fails. Do not launch new requests.
                    failure = failure or exc
                    continue
                completed = []
                for pair_id, decision in answers.items():
                    proposal = lookup[pair_id]
                    proposal.decision = decision
                    proposal.signals.append(Signal(kind="model", detail=decision))
                    completed.append(proposal)
                journal.save(completed)
                stats.decided += len(completed)
            if time.monotonic() >= next_progress:
                report()
                next_progress = time.monotonic() + 20
    report()
    if failure is not None:
        raise failure
    if stats.decided != stats.total:
        raise MatchBudgetExceeded("matching time budget reached; repeat the same command to resume")
