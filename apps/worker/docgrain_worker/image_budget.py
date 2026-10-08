"""Raster budgets shared by source preparation and Docling rendering."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageBudget:
    longest_side: int = 6000
    max_pixels: int = 40_000_000

    def __post_init__(self):
        if self.longest_side < 1 or self.max_pixels < 1:
            raise ValueError("image limits must be positive")

    @classmethod
    def from_env(cls):
        return cls(int(os.getenv("DOCGRAIN_IMAGE_MAX_SIDE", "6000")),
                   int(os.getenv("DOCGRAIN_IMAGE_MAX_PIXELS", "40000000")))

    def factor(self, width: float, height: float) -> float:
        if not all(math.isfinite(v) and v > 0 for v in (width, height)):
            raise ValueError("invalid image dimensions")
        return min(1.0, self.longest_side / max(width, height),
                   math.sqrt(self.max_pixels / (width * height)))

    def size(self, width: int, height: int) -> tuple[int, int]:
        factor = self.factor(width, height)
        return max(1, math.floor(width * factor)), max(1, math.floor(height * factor))


def budgeted_pipeline(events):
    """Keep Docling's own OCR coordinate mapping by changing its render scale too.

    The OCR stage processes each page serially. Both rendering and Docling's inverse
    box transform use the same scale; capping only the backend image breaks grounding.
    """
    from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

    class BudgetedPipeline(StandardPdfPipeline):
        # DocumentConverter builds pipelines as pipeline_cls(pipeline_options=...).
        def __init__(self, pipeline_options):
            super().__init__(pipeline_options)
            original = self.ocr_model
            self.ocr_model = BudgetedOcr(original, ImageBudget.from_env(), events)
            # Older StandardPdfPipeline implementations keep a build_pipe list.
            if hasattr(self, "build_pipe"):
                self.build_pipe = [self.ocr_model if model is original else model for model in self.build_pipe]

    return BudgetedPipeline


class BudgetedOcr:
    def __init__(self, model, budget, events=None):
        self.model = model
        self.budget = budget
        self.events = events if events is not None else []

    def __getattr__(self, name):
        return getattr(self.model, name)

    def __call__(self, conv_res, pages):
        for page in pages:
            original_scale = self.model.scale
            size = page._backend.get_size()
            scale = original_scale * self.budget.factor(
                size.width * original_scale, size.height * original_scale)
            self.model.scale = scale
            if scale < original_scale:
                self.events.append({"page_number": page.page_no,
                    "original_size": [math.ceil(size.width * original_scale), math.ceil(size.height * original_scale)],
                    "used_size": [round(size.width * scale), round(size.height * scale)],
                    "scale": scale / original_scale, "render_scale": scale})
            try:
                yield from self.model(conv_res, [page])
            finally:
                self.model.scale = original_scale


def render_settings(source, fmt, image_metadata=None):
    """Bound generated page/picture images before pipeline construction."""
    budget = ImageBudget.from_env()
    if image_metadata:
        sizes = [(image_metadata["input_width_px"], image_metadata["input_height_px"])]
    elif fmt.value == "pdf":
        import pymupdf
        with pymupdf.open(source.path) as pdf:
            sizes = [(p.rect.width, p.rect.height) for p in pdf]
    else:
        return 2.0, {}
    scale = min([2.0] + [2 * budget.factor(w * 2, h * 2) for w, h in sizes])
    return scale, {"longest_side": budget.longest_side, "max_pixels": budget.max_pixels,
                   "ocr_render": "per-page-budget-v1", "page_image_scale": scale}


def prepare_pdf(path, output):
    """Scale only unusually large physical pages, retaining native text/vectors.

    Ordinary scanned PDFs already have modest point dimensions. This extra guard
    bounds scale=1 renders too, before layout/table stages request any raster.
    """
    import pymupdf
    budget = ImageBudget.from_env()
    geometry = {}
    with pymupdf.open(path) as source:
        factors = [budget.factor(p.rect.width, p.rect.height) for p in source]
        if all(f == 1 for f in factors):
            return geometry
        with pymupdf.open() as prepared:
            for number, (page, factor) in enumerate(zip(source, factors, strict=True), 1):
                if factor == 1:
                    prepared.insert_pdf(source, from_page=number - 1, to_page=number - 1)
                    continue
                width, height = page.rect.width, page.rect.height
                used = budget.size(math.ceil(width), math.ceil(height))
                target = prepared.new_page(width=used[0], height=used[1])
                if page.get_contents():
                    target.show_pdf_page(target.rect, source, number - 1, keep_proportion=False)
                geometry[number] = {"original_size": [width, height], "used_size": list(used),
                                    "scale_x": used[0] / width, "scale_y": used[1] / height,
                                    "coordinate_frame": "original_visible_page"}
            prepared.save(output)
    return geometry


def restore_pdf_geometry(result, geometry):
    """All canonical text, cell and OCR boxes address the original visible page."""
    def locator(value):
        if not value or value.get("kind") != "pdf_raw":
            return
        transform = geometry.get(value["page_number"])
        if not transform or not value.get("bbox"):
            return
        box = value["bbox"]
        for key in ("l", "r"):
            box[key] /= transform["scale_x"]
        for key in ("t", "b"):
            box[key] /= transform["scale_y"]
        value["frame"] = "visible"

    for item in result.items:
        number = (item.locator or {}).get("page_number")
        locator(item.locator)
        if number in geometry:
            item.page_size = tuple(geometry[number]["original_size"])
        for row in item.cells:
            for cell in row:
                locator(cell.get("locator"))
        for value in item.field_locators.values():
            locator(value)
    for cell in result.source_metadata.get("ocr_cells", []):
        locator(cell.get("locator"))
    result.source_metadata["pdf_preparation"] = geometry
    result.processing_options["pdf_preparation"] = geometry
