from hashlib import sha256

import pytest
from docgrain_domain.canonical.live_sources import SourceObservation, changes
from docgrain_worker.source_adapters import FilesystemSource, IncompleteObservation


def observation(value=b"first"):
    digest = sha256(value).hexdigest()
    return SourceObservation(source_key="a.txt", uri="fixture://a", version=digest,
                             content_sha256=digest, byte_size=len(value))


def test_change_identity_scope_and_return_to_original():
    first = {"a.txt": observation()}
    a = changes("workspace", "connector", 1, {}, first)[0]
    b = changes("workspace", "connector", 2, first, {})[0]
    c = changes("workspace", "connector", 3, {}, first)[0]
    assert b.action == "delete" and b.observation is None
    assert a.document_id == b.document_id == c.document_id
    assert a.id != c.id
    assert changes("workspace", "connector", 1, {}, first) == [a]
    assert changes("other", "connector", 1, {}, first)[0].document_id != a.document_id


def test_filesystem_complete_scan_delete_and_changed_receipt(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"first")
    adapter = FilesystemSource(tmp_path)
    first = adapter.scan()
    assert adapter.read(first["a.txt"]) == b"first"
    path.write_bytes(b"second")
    with pytest.raises(IncompleteObservation, match="changed"):
        adapter.read(first["a.txt"])
    assert first != adapter.scan()
    path.unlink()
    assert adapter.scan() == {}
    tmp_path.rmdir()
    with pytest.raises(IncompleteObservation, match="unavailable"):
        adapter.scan()


def test_incomplete_inventory_never_returns_partial_state(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_bytes(b"first")
    adapter = FilesystemSource(tmp_path)
    inventory = adapter._inventory()
    calls = iter([inventory, {}])
    monkeypatch.setattr(adapter, "_inventory", lambda: next(calls))
    with pytest.raises(IncompleteObservation, match="tree changed"):
        adapter.scan()
