"""Display-only Excel formatting; never discovers cells or evaluates formulas."""

import re
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal


def display_value(value, number_format: str, *, fallback: str | None = None) -> str:
    if value is None:
        return fallback or ""
    fmt = number_format.split(";", 1)[0]
    if isinstance(value, (date, datetime, time)):
        formats = {
            "yyyy-mm-dd": "%Y-%m-%d", "yy-mm-dd": "%y-%m-%d",
            "dd/mm/yyyy": "%d/%m/%Y", "dd.mm.yyyy": "%d.%m.%Y",
            "mm/dd/yyyy": "%m/%d/%Y", "mm-dd-yy": "%m-%d-%y",
            "yyyy-mm-dd hh:mm:ss": "%Y-%m-%d %H:%M:%S",
            "h:mm:ss": "%H:%M:%S", "hh:mm:ss": "%H:%M:%S",
        }
        pattern = formats.get(fmt.lower())
        return value.strftime(pattern) if pattern else (fallback or value.isoformat())
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        match = re.fullmatch(r"(#,##)?0(?:\.(0+))?(%)?", fmt)
        if match:
            precision = len(match[2] or "")
            number = Decimal(str(value)) * (100 if match[3] else 1)
            number = number.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
            return format(number, f"{',' if match[1] else ''}.{precision}f") + ("%" if match[3] else "")
    return fallback if fallback is not None else str(value)
