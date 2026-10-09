"""Reading coverage is a parser signal, never approval or semantic verification."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256

from .docling_profiles import HARD_PAGE_CODES
from .quality import LOW_GRADES


def page_number(location) -> int | None:
    if location == "image":
        return 1
    if isinstance(location, str) and location.startswith("page:"):
        try:
            number = int(location.split(":")[1])
            return number if number > 0 else None
        except (ValueError, IndexError):
            pass
    return None


def reading_report(result, *, document_id: str, version_id: str, workspace_id: str,
                   source_sha256: str, mapping_issues=()) -> dict:
    """Use Docling grades, literal text and existing issues, with no extra inference."""
    paged = result.source_format.value in {"pdf", "png", "jpeg"}
    numbers = {int(n) for n in result.source_metadata.get("pages", {})}
    numbers.update(n for area in result.expected_areas if (n := page_number(area)))
    numbers.update(result.page_images)
    if result.source_format.value in {"png", "jpeg"}:
        numbers.add(1)
    if not paged:
        numbers = set()
    text_pages, picture_pages = set(), set()
    picture_counts = Counter()
    for item in result.items:
        number = (item.locator or {}).get("page_number", 1 if result.source_format.value in {"png", "jpeg"} else None)
        if item.kind == "picture":
            picture_pages.add(number)
            picture_counts[number] += 1
        if item.text.strip() or any(str(cell.get("text", "")).strip() for row in item.cells for cell in row):
            text_pages.add(number)
    codes = {n: set() for n in numbers}
    counts = Counter()
    seen = set()
    for issue in [*(i.__dict__ for i in result.issues), *mapping_issues]:
        code = issue["code"]
        identity = (code, issue.get("location"), issue.get("item_ref"), issue.get("stage"))
        if identity in seen:
            continue
        seen.add(identity)
        counts[code] += 1
        number = page_number(issue.get("location"))
        # Unresolved evidence boxes are counted, but they are not a reading problem of the page.
        if number in codes and code in HARD_PAGE_CODES | {"image_only_page", "no_ocr_text"}:
            codes[number].add(code)
    confidence = (result.source_metadata.get("docling_confidence") or {}).get("pages", {})
    for number in numbers:
        grade = confidence.get(str(number), confidence.get(number, {}))
        if grade.get("low_grade") in LOW_GRADES or grade.get("mean_grade") in LOW_GRADES:
            codes[number].add("docling_low_grade")
        if number not in text_pages:
            codes[number].add("textless_page")
            if number in picture_pages:
                codes[number].add("image_only_page")
        if result.source_format.value in {"png", "jpeg"}:
            codes[number].add("image_file")
    report = {
        "format": "docgrain.reading-quality", "version": 1,
        "document_id": document_id, "version_id": version_id, "workspace_id": workspace_id,
        "source_sha256": source_sha256, "source_format": result.source_format.value,
        "total_pages": len(numbers) if paged else None,
        "local_status": result.status, "model_enabled": False,
        "issue_counts": dict(sorted(counts.items())),
        "unpaged_images": picture_counts.get(None, 0) if not paged else 0,
        "pages": [{"page_number": n, "codes": sorted(codes[n]),
                   "picture_count": 1 if result.source_format.value in {"png", "jpeg"} else picture_counts[n],
                   "state": "waiting_model" if codes[n] else "read_local",
                   "image_sha256": sha256(result.page_images[n]).hexdigest() if n in result.page_images else None,
                   "model_reading": None,
                   # Pictures on otherwise readable pages: Docling picture description (PictureDescriptionApiOptions).
                   "picture_state": "waiting_model" if not codes[n] and picture_counts[n] else None,
                   "picture_reading": None} for n in sorted(numbers)],
    }
    return summarize(report)


def summarize(report: dict) -> dict:
    pages = report["pages"]
    report["pages_read_well"] = sum(p["state"] == "read_local" for p in pages)
    report["pages_read_by_model"] = sum(p["state"] == "needs_review" for p in pages)
    report["pages_waiting_model"] = sum(p["state"] in {"waiting_model", "budget_deferred", "model_failed", "image_unavailable"} for p in pages)
    report["low_confidence_pages"] = [p["page_number"] for p in pages if set(p["codes"]) & {"docling_low_grade", "ocr_low_confidence", "low_text_page"}]
    report["image_only_pages"] = [p["page_number"] for p in pages if "image_only_page" in p["codes"]]
    report["images_not_understood"] = report.get("unpaged_images", 0) + sum(
        p.get("picture_count", 0) for p in pages
        if p["state"] != "needs_review" and p.get("picture_state") not in {"needs_review", "not_needed"})
    report["pictures_read_by_model"] = sum(p.get("picture_state") == "needs_review" for p in pages)
    report["unresolved_regions"] = report["issue_counts"].get("bbox_unresolved", 0)
    report["column_table_conflicts"] = sum(report["issue_counts"].get(c, 0) for c in ("column_text_conflict", "table_fallback_geometry"))
    if report["total_pages"] is None:
        report["summary"] = "İçerik okundu" if report["local_status"] == "complete" else "İçerik kontrol edilmeli"
    else:
        read = report["pages_read_well"]
        last = read % 10 or read % 100 or (100 if read % 1000 else 1000)
        suffix = {0: "ı", 1: "i", 2: "si", 3: "ü", 4: "ü", 5: "i", 6: "sı", 7: "si", 8: "i", 9: "u",
                  10: "u", 20: "si", 30: "u", 40: "ı", 50: "si", 60: "ı", 70: "i", 80: "i", 90: "ı", 100: "ü", 1000: "i"}[last if read else 0]
        report["summary"] = f"{report['total_pages']} sayfanın {read}'{suffix} okundu"
        if report["pages_waiting_model"]:
            report["summary"] += f" · {report['pages_waiting_model']} sayfa model bekliyor"
        if report["pages_read_by_model"]:
            report["summary"] += f" · {report['pages_read_by_model']} sayfa inceleme bekliyor"
        if report["pictures_read_by_model"]:
            report["summary"] += f" · {report['pictures_read_by_model']} sayfadaki görseller inceleme bekliyor"
    return report
