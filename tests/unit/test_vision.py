from pathlib import Path

from docgrain_worker.vision import VisionPage, extract_pages


def page(number: int) -> VisionPage:
    return VisionPage(
        page_number=number,
        language="tr",
        page_title=f"Page {number}",
        markdown=f"# Page {number}",
        regions=[],
        table_count=0,
        asset_count=0,
    )


def test_vision_pages_use_four_worker_bounded_retry_orchestration() -> None:
    calls: dict[int, int] = {}

    class Extractor:
        def extract(self, _path: Path, page_number: int) -> VisionPage:
            calls[page_number] = calls.get(page_number, 0) + 1
            if page_number == 2 and calls[page_number] < 3:
                raise TimeoutError("temporary timeout")
            return page(page_number)

    results, failures = extract_pages(
        [(1, Path("1.png")), (2, Path("2.png"))],
        Extractor(),
        retry_delay=lambda _attempt: None,
    )

    assert sorted(results) == [1, 2]
    assert failures == {}
    assert calls == {1: 1, 2: 3}


def test_vision_page_is_reported_after_three_failed_attempts() -> None:
    calls = 0

    class Extractor:
        def extract(self, _path: Path, _page_number: int) -> VisionPage:
            nonlocal calls
            calls += 1
            raise RuntimeError("provider unavailable")

    results, failures = extract_pages(
        [(7, Path("7.png"))],
        Extractor(),
        retry_delay=lambda _attempt: None,
    )

    assert results == {}
    assert failures == {7: "provider unavailable"}
    assert calls == 3
