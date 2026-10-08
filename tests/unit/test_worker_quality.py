from docgrain_domain.source_format import SourceFormat
from docgrain_worker.docling_profiles import hard_pages
from docgrain_worker.quality import confidence_issues, page_failures
from docgrain_worker.structural import StructuralParseResult, _issue


def test_confidence_grades_drive_existing_issue_codes_without_cell_thresholds():
    report = {"pages": {
        "1": {"low_grade": "excellent", "mean_grade": "good", "ocr_score": 0.1},
        "2": {"low_grade": "poor", "ocr_score": 0.3, "layout_score": 0.9, "parse_score": 0.8},
        "3": {"low_grade": "fair", "ocr_score": 0.9, "layout_score": 0.3},
        "4": {"low_grade": "poor", "ocr_score": None, "layout_score": None},
    }}
    issues = confidence_issues(report, SourceFormat.PDF)
    assert [(i.location, i.code) for i in issues] == [
        ("page:2", "ocr_low_confidence"), ("page:3", "low_text_page"), ("page:4", "low_text_page")]
    assert all(i.impact == "page" and "Docling confidence" in i.reason for i in issues)
    result = StructuralParseResult(SourceFormat.PDF, "docling", "2.130.0", "partial", [], [], [], issues)
    assert set(hard_pages(result)) == {2, 3, 4}
    assert [f["page_number"] for f in page_failures(result)] == [2, 3, 4]
    assert "poor" in page_failures(result)[0]["reason"]


def test_images_and_missing_reports():
    assert confidence_issues({}, SourceFormat.PNG) == []
    issues = confidence_issues({"pages": {"1": {"low_grade": "poor"}}}, SourceFormat.PNG)
    assert issues[0].location == "image" and issues[0].code == "low_text_page"


def test_missing_page_is_an_operational_failure_and_good_ocr_stays_unreviewed():
    issues = [_issue(SourceFormat.PDF, "missing_page", "Missing geometry", location="page:2"),
              _issue(SourceFormat.PDF, "ocr_needs_review", "Unreviewed", location="page:1")]
    result = StructuralParseResult(SourceFormat.PDF, "docling", "2.130.0", "partial", [], [], [], issues)
    assert [f["page_number"] for f in page_failures(result)] == [2]
