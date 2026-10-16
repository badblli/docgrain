"""WP115: small, offline name dictionary; comparison keys never replace source values.

Only the listed cuisine/type words are translated. Unknown words, numbers and brand
names stay in the key. Generic-only labels have no distinguishing key. This is a
candidate hint, never sufficient evidence to approve identity.
"""

import re
import unicodedata

from .normalize import format_key

GENERIC_WORDS = frozenset({
    "restoran", "restorani", "restaurant", "restaurants", "restaurante", "restaurantes",
    "ресторан", "ресторана", "бар", "bar", "bari", "bars", "snack", "snackbar",
    "imbiss", "закусочная", "the",
})
# Explicit EN/TR/DE/RU equivalences, deliberately bounded (no general translation).
CUISINE_WORDS = {
    "fish": ("fish", "balik", "fisch", "рыба", "рыбный"),
    "chinese": ("chinese", "cin", "cinli", "chinesisch", "chinesisches", "китайский"),
    "italian": ("italian", "italyan", "italienisch", "italienisches", "итальянский"),
    "steakhouse": ("steak", "steakhouse", "steakhaus", "стейк", "стейкхаус"),
    "bistro": ("bistro", "бистро"),
}
_CATEGORIES = {
    "restaurant": ("restaurant", "restoran", "restorani", "restaurante", "ресторан"),
    "bar": ("bar", "bari", "бар"),
}
CATEGORY_FIELDS = frozenset({"kind", "category", "cuisine", "type"})


def words(value):
    if not isinstance(value, str):
        return []
    text = unicodedata.normalize("NFKC", value).casefold().replace("ı", "i").replace("ß", "ss")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"\bsteak\s+house\b", "steakhouse", text)
    return re.findall(r"[^\W_]+", text)


_CUISINES = {" ".join(words(word)): key for key, variants in CUISINE_WORDS.items() for word in variants}
_CATEGORY_WORDS = {" ".join(words(word)): key for key, variants in _CATEGORIES.items() for word in variants}


def place_name(value):
    return " ".join(sorted(_CUISINES.get(word, word) for word in words(value)
                           if word not in GENERIC_WORDS))


def name_keys(values):
    return {key for value in values if (key := place_name(value))}


def record_name_keys(record):
    return name_keys([record.name.value, *(f.name.value for f in record.i18n.values() if f.name)])


def comparison_key(value, field):
    if field in CATEGORY_FIELDS and isinstance(value, str):
        tokens = words(value)
        value = " ".join(_CATEGORY_WORDS.get(t, _CUISINES.get(t, t)) for t in tokens)
    return format_key(value, field)


def field_support(left, right):
    """Compare all common non-name values, including i18n; any difference vetoes approval."""
    shared, conflicts = [], []
    for field in sorted(left.keys() & right.keys()):
        a = {comparison_key(v, field) for v in left[field]}
        b = {comparison_key(v, field) for v in right[field]}
        if not a or not b:
            continue
        if len(a) == len(b) == 1 and a == b:
            shared.append(field)
        else:
            conflicts.append(field)
    return shared, conflicts


def record_values(record):
    # Runtime collections may call their identity "title", "label", etc.; .name is
    # the runtime's identity accessor. Do not count it as independent support.
    identity = next((key for key in record.field_names()
                     if getattr(record, key) == record.name), "name")
    values = {}
    for fields in [record, *record.i18n.values()]:
        for key in record.field_names():
            fact = getattr(fields, key, None)
            if key != identity and fact is not None:
                values.setdefault(key, []).append(fact.value)
    return values
