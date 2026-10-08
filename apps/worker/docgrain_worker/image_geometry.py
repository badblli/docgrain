"""Reversible EXIF geometry; canonical boxes always address original encoded pixels."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO

from docgrain_domain.canonical import NormalizedBox
from PIL import Image, ImageOps

from .image_budget import ImageBudget


def orient_point(x: float, y: float, orientation: int) -> tuple[float, float]:
    transforms = {
        1: (x, y),
        2: (1 - x, y),
        3: (1 - x, 1 - y),
        4: (x, 1 - y),
        5: (y, x),
        6: (1 - y, x),
        7: (1 - y, 1 - x),
        8: (y, 1 - x),
    }
    if orientation not in transforms:
        raise ValueError("invalid EXIF orientation")
    return transforms[orientation]


def transform_box(
    box: NormalizedBox, orientation: int, *, inverse: bool = False
) -> NormalizedBox:
    if inverse:
        orientation = {6: 8, 8: 6}.get(orientation, orientation)
    corners = [
        orient_point(x, y, orientation)
        for x in (box.x, box.x + box.width)
        for y in (box.y, box.y + box.height)
    ]
    left, top = min(x for x, _ in corners), min(y for _, y in corners)
    right, bottom = max(x for x, _ in corners), max(y for _, y in corners)
    return NormalizedBox(x=left, y=top, width=right - left, height=bottom - top)


def prepare_image(data: bytes, *, budget: ImageBudget | None = None) -> tuple[bytes, dict]:
    budget = budget or ImageBudget.from_env()
    with Image.open(BytesIO(data)) as original:
        width, height = original.size
        orientation = original.getexif().get(274, 1)
        if orientation not in range(1, 9):
            raise ValueError("invalid EXIF orientation")
        # JPEG draft decoding avoids allocating the full RGB map before shrinking.
        target = budget.size(width, height)
        original.draft("RGB", target)
        original.thumbnail(target, Image.Resampling.LANCZOS, reducing_gap=3.0)
        # Composite only the reduced pixels; retain the untouched source separately.
        oriented = ImageOps.exif_transpose(original).convert("RGBA")
        rgb = Image.new("RGB", oriented.size, "white")
        rgb.paste(oriented, mask=oriented.getchannel("A"))
        output = BytesIO()
        rgb.save(output, format="PNG")
        prepared = output.getvalue()
        return prepared, {
            "width_px": width,
            "height_px": height,
            "exif_orientation": orientation,
            "input_width_px": rgb.width,
            "input_height_px": rgb.height,
            "scale_x": rgb.width / (height if orientation >= 5 else width),
            "scale_y": rgb.height / (width if orientation >= 5 else height),
            "downscaled": target != (width, height),
            "budget": {"longest_side": budget.longest_side, "max_pixels": budget.max_pixels},
            "source_sha256": sha256(data).hexdigest(),
            "input_sha256": sha256(prepared).hexdigest(),
            "transform": "budget-lanczos-exif-transpose-rgba-white-rgb-v2",
            "coordinate_frame": "original_encoded_pixels",
            "input_coordinate_frame": "exif_transposed_pixels",
        }


def image_locator(raw: dict, page_size: tuple[float, float], metadata: dict) -> dict:
    width, height = page_size
    if width <= 0 or height <= 0:
        raise ValueError("image parser page dimensions unavailable")
    left, right = float(raw["l"]) / width, float(raw["r"]) / width
    top, bottom = float(raw["t"]) / height, float(raw["b"]) / height
    if raw.get("coord_origin") == "BOTTOMLEFT":
        top, bottom = 1 - top, 1 - bottom
    top, bottom = sorted((top, bottom))
    # Subpixel rounding may protrude slightly; larger errors must remain explicit failures.
    if min(left, top) < -1e-6 or max(right, bottom) > 1 + 1e-6:
        raise ValueError("image bbox exceeds verified image frame")
    left, top, right, bottom = max(0, left), max(0, top), min(1, right), min(1, bottom)
    box = transform_box(
        NormalizedBox(x=left, y=top, width=right - left, height=bottom - top),
        metadata["exif_orientation"],
        inverse=True,
    )
    return {
        "kind": "image_region",
        "width_px": metadata["width_px"],
        "height_px": metadata["height_px"],
        "exif_orientation": metadata["exif_orientation"],
        "bbox": box.model_dump(mode="json"),
    }
