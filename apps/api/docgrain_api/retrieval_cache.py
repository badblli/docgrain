"""Byte-bound LRU of immutable revision views; heads are always read from storage."""

from collections import OrderedDict
from threading import Lock


class RevisionCache:
    def __init__(self, max_bytes=32*1024*1024):
        self.max_bytes = max_bytes
        self._items = OrderedDict()
        self._bytes = 0
        self._lock = Lock()

    def get(self, key):
        with self._lock:
            if key not in self._items:
                return None
            view, _size = self._items[key]
            self._items.move_to_end(key)
            return view.model_copy(deep=True)

    def put(self, key, view):
        size = len(view.model_dump_json().encode())
        if size > self.max_bytes:
            return
        with self._lock:
            if key in self._items:
                self._bytes -= self._items.pop(key)[1]
            self._items[key] = (view.model_copy(deep=True), size)
            self._bytes += size
            while self._bytes > self.max_bytes:
                _, (_view, removed) = self._items.popitem(last=False)
                self._bytes -= removed

    def clear(self):
        with self._lock:
            self._items.clear()
            self._bytes = 0
