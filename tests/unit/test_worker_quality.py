from docgrain_worker.quality import missing_extraction_pages, page_failures


def test_zero_sized_or_absent_parser_pages_fail_quality() -> None:
    structured = {
        "pages": {
            "1": {"size": {"width": 595.0, "height": 842.0}},
            "2": {"size": {"width": 0.0, "height": 0.0}},
        }
    }

    assert missing_extraction_pages(structured, rendered_page_count=3) == [2, 3]


def test_blank_page_with_valid_dimensions_is_not_a_failure() -> None:
    structured = {"pages": {"1": {"size": {"width": 595, "height": 842}}}}

    assert missing_extraction_pages(structured, rendered_page_count=1) == []


def test_quality_failures_preserve_render_and_request_multimodal_retry() -> None:
    assert page_failures([4]) == [
        {
            "page_number": 4,
            "stage": "extract",
            "reason": "Parser did not produce a valid page representation.",
            "resolution": "Page render was preserved; multimodal retry is required.",
        }
    ]
