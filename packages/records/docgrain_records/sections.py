"""Bounded compact-context sections, retaining original block keys and footer pins."""

import re
from dataclasses import dataclass

BLOCK_MARKER = re.compile(r"(?m)^\[§(\d+) p\.[^\r\n]*\]\r?$")
FOOTER_MARKER = re.compile(r"(?m)^## Kaynak anahtarları\r?$")


@dataclass(frozen=True)
class Section:
    index: int
    context: str
    source_keys: tuple[str, ...]


def _pieces(text: str, limit: int) -> list[str]:
    """Prefer line/word boundaries, never truncate an oversized block or table."""
    pieces = []
    while len(text) > limit:
        cut = text.rfind("\n", limit // 2, limit + 1)
        if cut < 0:
            cut = text.rfind(" ", limit // 2, limit + 1)
        cut = cut + 1 if cut >= 0 else limit
        pieces.append(text[:cut])
        text = text[cut:]
    if text:
        pieces.append(text)
    return pieces


def split_context(context: str, target_chars: int = 8000) -> list[Section]:
    """Prefer headings after ~6k chars, otherwise whole-block ranges up to ~10k.

    Oversized blocks are continued under the same §N key, with original table headers
    repeated when available. Only each section's source-key mappings are included.
    Plain caller contexts use line/word boundaries and retain descriptive locators.
    """
    if not 1000 <= target_chars <= 10000:
        raise ValueError("section size must be between 1000 and 10000 characters")
    if not context.strip():
        raise ValueError("source context is empty")
    minimum, maximum = target_chars * 3 // 4, target_chars * 5 // 4
    footer = FOOTER_MARKER.search(context)
    boundary = footer.start() if footer else len(context)
    markers = [m for m in BLOCK_MARKER.finditer(context) if m.start() < boundary]
    if len(context) <= maximum:
        return [Section(1, context, tuple(f"§{m.group(1)}" for m in markers))]
    if not markers:
        return [Section(i + 1, piece, ()) for i, piece in enumerate(_pieces(context, target_chars))]

    prefix = context[:markers[0].start()]
    mappings = {}
    for line in context[boundary:].splitlines():
        match = re.match(r"^(§\d+) → ", line)
        if match:
            mappings[match.group(1)] = line

    def render(parts):
        keys = tuple(dict.fromkeys(key for key, _ in parts))
        text = prefix + "".join(body for _, body in parts)
        if footer:
            text += "\n## Kaynak anahtarları\n" + "\n".join(
                mappings[key] for key in keys if key in mappings
            ) + "\n"
        return text, keys

    units = []
    for i, marker in enumerate(markers):
        stop = markers[i + 1].start() if i + 1 < len(markers) else boundary
        key, block = f"§{marker.group(1)}", context[marker.start():stop]
        if len(render([(key, block)])[0]) <= maximum:
            units.append((key, block))
            continue
        label = context[marker.start():marker.end()] + "\n"
        body = context[marker.end():stop].lstrip("\r\n")
        # A continuation of a long table still needs its source column names.
        table = re.search(r"(?m)^(\|[^\n]*\n\|[ :|\-]+\|[^\n]*\n)", body)
        header = table.group(1) if table else ""
        overhead = len(render([(key, label + header)])[0])
        if overhead >= target_chars:
            raise ValueError("source block metadata exceeds the section size")
        for j, piece in enumerate(_pieces(body, target_chars - overhead)):
            units.append((key, label + (header if j else "") + piece + "\n"))

    groups, current = [], []
    for unit in units:
        heading = bool(re.match(r"^\[§[^\n]+\]\r?\n\s*#{1,6} ", unit[1]))
        size = len(render(current)[0]) if current else 0
        if current and (len(render([*current, unit])[0]) > maximum or heading and size >= minimum
                        or any(key == unit[0] for key, _ in current)):
            groups.append(current)
            current = []
        current.append(unit)
    if current:
        groups.append(current)
    return [Section(i + 1, *render(group)) for i, group in enumerate(groups)]
