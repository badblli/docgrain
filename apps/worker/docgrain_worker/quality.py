"""Adapt Docling confidence grades to the existing reading-report issue codes."""

from .structural import _issue

LOW_GRADES = {"poor", "fair", "low"}


def confidence_issues(report, fmt):
    issues = []
    for number, page in report.get("pages", {}).items():
        if page.get("low_grade") not in LOW_GRADES and page.get("mean_grade") not in LOW_GRADES:
            continue
        # Grade comes from Docling, not a second threshold applied to cell scores.
        ocr = page.get("ocr_score")
        scores = [page.get(name) for name in ("ocr_score", "layout_score", "parse_score", "table_score")]
        scores = [score for score in scores if isinstance(score, (int, float))]
        code = "ocr_low_confidence" if ocr is not None and scores and ocr == min(scores) else "low_text_page"
        location = f"page:{number}" if fmt.value == "pdf" else "image"
        issues.append(_issue(fmt, code,
            f"Docling confidence: low={page.get('low_grade')}, mean={page.get('mean_grade')}; source review required",
            location=location, impact="page"))
    return issues


def page_failures(result):
    """Keep the job contract, with Docling-derived issues as the reading signal."""
    from .docling_profiles import hard_pages
    return [{"page_number": number, "stage": "extract",
             "reason": "; ".join(issue.reason for issue in result.issues
                                 if issue.location == f"page:{number}" and issue.code in codes),
             "resolution": "Kaynak sayfayı kontrol edin; otomatik kabul yapılmadı."}
            for number, codes in sorted(hard_pages(result).items())]
