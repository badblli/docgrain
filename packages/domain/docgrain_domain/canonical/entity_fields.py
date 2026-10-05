"""RFC 6901 field paths, including nested arrays and empty containers."""

from pydantic import JsonValue


def pointer(tokens) -> str:
    return "".join("/" + str(token).replace("~", "~0").replace("/", "~1") for token in tokens)


def leaf_pointers(value: JsonValue, tokens=()) -> set[str]:
    if isinstance(value, dict) and value:
        return set().union(*(leaf_pointers(child, (*tokens, key)) for key, child in value.items()))
    if isinstance(value, list) and value:
        return set().union(*(leaf_pointers(child, (*tokens, index)) for index, child in enumerate(value)))
    return {pointer(tokens)}


def resolve_pointer(value: JsonValue, path: str) -> JsonValue:
    if path == "":
        return value
    if not path.startswith("/"):
        raise ValueError("field path must be a JSON Pointer")
    for encoded in path[1:].split("/"):
        index = 0
        while index < len(encoded):
            if encoded[index] == "~":
                if index + 1 == len(encoded) or encoded[index + 1] not in "01":
                    raise ValueError("invalid JSON Pointer escape")
                index += 1
            index += 1
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isascii() and token.isdigit() and str(int(token)) == token and int(token) < len(value):
            value = value[int(token)]
        else:
            raise ValueError(f"field pointer does not resolve: {path}")
    return value
