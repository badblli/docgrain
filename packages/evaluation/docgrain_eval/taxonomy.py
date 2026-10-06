"""Load the single vocabulary in source trees and packaged distributions."""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_taxonomy() -> dict:
    packaged = Path(__file__).with_name("taxonomy.json")
    source = Path(__file__).parents[2] / "records" / "taxonomy.json"
    return json.loads((packaged if packaged.exists() else source).read_text(encoding="utf-8"))


def taxonomy_prompt(collection: str | None = None) -> str:
    vocabulary = load_taxonomy()
    collections = vocabulary["collections"]
    selected = {collection: collections[collection]} if collection else collections
    return "Vocabulary and boundaries:\n" + json.dumps(
        {"rules": vocabulary["rules"], "collections": selected}, ensure_ascii=False) + "\n"
