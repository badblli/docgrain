"""In-memory fixtures.

These are the exact shapes the review console was designed against. They let
the UI be built and demoed before PostgreSQL, the worker and object storage
exist. Every reader goes through the repository functions at the bottom, so
swapping in a real database means replacing this module, not the routers.
"""

from __future__ import annotations

import zlib
from datetime import UTC, datetime
from itertools import pairwise

from docgrain_domain import (
    STAGE_ORDER,
    Asset,
    BoundaryPoint,
    Chunk,
    Document,
    DocumentVersion,
    Job,
    JobStage,
    JobStatus,
    Neighbor,
    Page,
    PageFailure,
    ProviderHealth,
    QualityFlag,
    SplitStrategy,
    StageRun,
    StageStatus,
    TableArtifact,
    VersionStatus,
)
from docgrain_domain.models import DiffEntry, VersionDiff

WS = "ws_luwi"
DOC = "doc_7fk2"
V2 = "dver_2"
V1 = "dver_1"
BUCKET = f"s3://docgrain/{DOC}/{V2}"
SPLIT_THRESHOLD = 0.55


def _at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2025, 8, day, hour, minute, tzinfo=UTC)


DOCUMENTS: list[Document] = [
    Document(
        id=DOC,
        workspace_id=WS,
        title="Finansal İstikrar Raporu 2025-II",
        filename="fsr-2025-2.pdf",
        mime_type="application/pdf",
        latest_version_id=V2,
        version_count=2,
        created_at=_at(19, 9, 12),
        updated_at=_at(30, 14, 6),
    )
]

VERSIONS: list[DocumentVersion] = [
    DocumentVersion(
        id=V2,
        document_id=DOC,
        workspace_id=WS,
        revision=2,
        content_sha256="4f9c" + "0" * 56 + "b18e",
        source_uri=f"{BUCKET}/original.pdf",
        byte_size=13_002_342,
        page_count=48,
        chunk_count=44,
        table_count=3,
        asset_count=4,
        status=VersionStatus.DONE,
        parser="docling-2.19",
        vision_provider="gemini-2.5-flash",
        created_at=_at(30, 14, 1),
        published_at=_at(30, 14, 6),
    ),
    DocumentVersion(
        id=V1,
        document_id=DOC,
        workspace_id=WS,
        revision=1,
        content_sha256="1ab7" + "0" * 56 + "c033",
        source_uri=f"s3://docgrain/{DOC}/{V1}/original.pdf",
        byte_size=12_884_901,
        page_count=48,
        chunk_count=41,
        table_count=1,
        asset_count=2,
        status=VersionStatus.DONE,
        parser="docling-2.14",
        vision_provider=None,
        created_at=_at(19, 9, 12),
        published_at=_at(19, 9, 19),
    ),
]

_PAGE_SPEC: list[tuple[int, str, float, list[QualityFlag], bool]] = [
    (1, "docling-2.19", 0.99, [], False),
    (2, "docling-2.19", 0.97, [], False),
    (3, "docling-2.19", 0.96, [], False),
    (4, "docling-2.19", 0.91, [QualityFlag.TABLE_HEAVY], False),
    (5, "docling-2.19", 0.88, [QualityFlag.FIGURE], True),
    (6, "docling-2.19", 0.83, [QualityFlag.LAYOUT_COMPLEX], False),
    (
        7,
        "qwen2.5-vl-3b-instruct",
        0.41,
        [QualityFlag.SCANNED, QualityFlag.LOW_CONFIDENCE, QualityFlag.VISION_FALLBACK],
        True,
    ),
    (8, "docling-2.19", 0.95, [], False),
]

PAGES: list[Page] = [
    Page(
        id=f"pg_{number:04d}",
        document_version_id=V2,
        page_number=number,
        render_uri=f"{BUCKET}/pages/{number:04d}.png",
        width=1654,
        height=2339,
        dpi=200,
        parser=parser,
        confidence=confidence,
        char_count=1284,
        block_count=9,
        quality_flags=flags,
        markdown=None,
        derived_content=derived,
    )
    for number, parser, confidence, flags, derived in _PAGE_SPEC
]

TABLES: list[TableArtifact] = [
    TableArtifact(
        id="tbl_01",
        document_version_id=V2,
        page_number=4,
        title="Tablo 2.1 — Aktif kalitesi göstergeleri",
        row_count=4,
        column_count=4,
        confidence=0.94,
        header=["Dönem", "TGA oranı (%)", "Karşılık (%)", "Yakın izleme (%)"],
        rows=[
            ["2023-IV", "1,62", "82,4", "3,91"],
            ["2024-II", "1,74", "80,9", "4,15"],
            ["2024-IV", "1,88", "79,3", "4,52"],
            ["2025-II", "2,07", "77,8", "4,88"],
        ],
    ),
    TableArtifact(
        id="tbl_02",
        document_version_id=V2,
        page_number=6,
        title="Tablo 3.1 — Hanehalkı yükümlülükleri",
        row_count=3,
        column_count=3,
        confidence=0.87,
        header=["Kalem", "2024", "2025"],
        rows=[
            ["Konut kredisi", "1.284", "1.512"],
            ["İhtiyaç kredisi", "2.031", "2.388"],
            ["Kredi kartı", "1.907", "2.640"],
        ],
    ),
    TableArtifact(
        id="tbl_03",
        document_version_id=V2,
        page_number=8,
        title="Tablo A.1 — Veri kaynakları",
        row_count=3,
        column_count=2,
        confidence=0.79,
        header=["Seri", "Kaynak"],
        rows=[["TGA oranı", "BDDK"], ["Kredi büyümesi", "TCMB EVDS"], ["Hanehalkı geliri", "TÜİK"]],
    ),
]

ASSETS: list[Asset] = [
    Asset(
        id="ast_01",
        document_version_id=V2,
        page_number=5,
        mime_type="image/png",
        storage_uri=f"{BUCKET}/assets/ast_01.png",
        width=1240,
        height=720,
        byte_size=188_416,
        sha256="9c4f" + "0" * 56 + "a71b",
        caption="Yıllık kredi büyümesi: ticari ve tüketici kredileri.",
        caption_is_derived=True,
    ),
    Asset(
        id="ast_02",
        document_version_id=V2,
        page_number=5,
        mime_type="image/png",
        storage_uri=f"{BUCKET}/assets/ast_02.png",
        width=980,
        height=640,
        byte_size=123_904,
        sha256="2ea8" + "0" * 56 + "4d10",
        caption="Sektör bazında TGA oranı dağılımı, 2025-II.",
        caption_is_derived=True,
    ),
    Asset(
        id="ast_03",
        document_version_id=V2,
        page_number=1,
        mime_type="image/png",
        storage_uri=f"{BUCKET}/assets/ast_03.png",
        width=420,
        height=420,
        byte_size=22_528,
        sha256="71bc" + "0" * 56 + "9f02",
        caption="Kurum amblemi (kapak).",
        caption_is_derived=False,
    ),
    Asset(
        id="ast_04",
        document_version_id=V2,
        page_number=7,
        mime_type="image/png",
        storage_uri=f"{BUCKET}/assets/ast_04.png",
        width=2480,
        height=3508,
        byte_size=1_468_006,
        sha256="55da" + "0" * 56 + "08e7",
        caption="Taranmış ek sayfa; görsel model tarafından okundu.",
        caption_is_derived=True,
    ),
]

_CHUNK_SPEC: list[tuple[str, int, list[str], list[int], int, list[str], list[str], str]] = [
    ("chk_01", 0, ["Finansal İstikrar Raporu", "Yönetici Özeti"], [1, 2], 118, [], [],
     "Bu raporda finansal istikrarı etkileyen makrofinansal gelişmeler değerlendirilmektedir."),
    ("chk_02", 0, ["Finansal İstikrar Raporu", "Yönetici Özeti", "Temel bulgular"], [2], 96, [], [],
     "Takipteki alacak oranındaki artış ılımlıdır, karşılık oranları yüksektir."),
    ("chk_03", 1, ["Finansal İstikrar Raporu", "1. Makrofinansal Görünüm"], [3], 142, [], [],
     "Küresel finansal koşullar 2025 yılının ikinci yarısında bir miktar gevşemiştir."),
    ("chk_04", 1, ["Finansal İstikrar Raporu", "1. Makrofinansal Görünüm", "1.1 Küresel gelişmeler"], [3], 131, [], [],
     "Uzun vadeli tahvil getirilerindeki oynaklık yüksek seyretmeye devam etmektedir."),
    ("chk_05", 1, ["Finansal İstikrar Raporu", "1. Makrofinansal Görünüm", "1.2 Yurt içi talep"], [3, 4], 127, [], [],
     "Cari işlemler dengesindeki iyileşme dışsal şoklara karşı tamponları güçlendirmiştir."),
    ("chk_06", 2, ["Finansal İstikrar Raporu", "2. Bankacılık Sektörü", "2.1 Aktif kalitesi"], [4], 158, [], ["tbl_01"],
     "Takipteki alacak oranı sektör genelinde ılımlı bir artış göstermiştir."),
    ("chk_07", 2, ["Finansal İstikrar Raporu", "2. Bankacılık Sektörü", "2.1 Aktif kalitesi"], [4, 5], 149, ["ast_01"], ["tbl_01"],
     "Kur etkisinden arındırılmış yıllık kredi büyümesi yavaşlamıştır."),
    ("chk_08", 2, ["Finansal İstikrar Raporu", "2. Bankacılık Sektörü", "Grafik 2.3"], [5], 88, ["ast_01", "ast_02"], [],
     "Grafik 2.3, ticari ve tüketici kredi büyümesini zaman serisi olarak göstermektedir."),
    ("chk_09", 3, ["Finansal İstikrar Raporu", "3. Hanehalkı Borçluluğu"], [6], 136, [], ["tbl_02"],
     "Hanehalkı yükümlülüklerinin harcanabilir gelire oranı düşük seviyesini korumaktadır."),
    ("chk_10", 4, ["Finansal İstikrar Raporu", "Ek A. Yöntem Notu"], [7, 8], 104, ["ast_04"], ["tbl_03"],
     "Örneklem 2015-2025 dönemi için mevduat ve katılım bankalarını kapsamaktadır."),
]

CHUNK_GROUP: dict[str, int] = {spec[0]: spec[1] for spec in _CHUNK_SPEC}

CHUNKS: list[Chunk] = [
    Chunk(
        id=chunk_id,
        document_id=DOC,
        document_version_id=V2,
        workspace_id=WS,
        text=text,
        embedding_text=" > ".join(heading_path) + "\n\n" + text,
        heading_path=heading_path,
        page_numbers=pages,
        source_uri=f"{BUCKET}/original.pdf",
        page_image_uris=[f"{BUCKET}/pages/{page:04d}.png" for page in pages],
        asset_ids=assets,
        table_ids=tables,
        token_count=tokens,
        split_strategy=SplitStrategy.TOKEN_FALLBACK if tokens > 150 else SplitStrategy.HEADING,
        derived=chunk_id == "chk_08",
        metadata={"parser": "docling-2.19", "overlap_tokens": 80 if tokens > 150 else 0},
    )
    for chunk_id, _group, heading_path, pages, tokens, assets, tables, text in _CHUNK_SPEC
]


def cosine(left: str, right: str) -> float:
    """Deterministic stand-in for a real vector comparison.

    Chunks in the same section score high, neighbouring sections score in the
    middle, distant sections score low -- the shape a real embedding space
    produces, so the UI can be built and reviewed before embeddings exist.
    """
    if left == right:
        return 1.0
    a, b = CHUNK_GROUP[left], CHUNK_GROUP[right]
    # crc32, not hash(): str hashing is salted per process, which would make
    # the same chunk pair score differently after every restart.
    key = "|".join(sorted((left, right))).encode()
    noise = (zlib.crc32(key) % 10_000) / 10_000
    distance = abs(a - b)
    if distance == 0:
        return round(0.79 + noise * 0.13, 3)
    if distance == 1:
        return round(0.44 + noise * 0.17, 3)
    return round(0.16 + noise * 0.21, 3)


def neighbors(chunk_id: str, limit: int = 5) -> list[Neighbor]:
    scored = [
        Neighbor(chunk_id=other.id, score=cosine(chunk_id, other.id), heading_path=other.heading_path)
        for other in CHUNKS
        if other.id != chunk_id
    ]
    scored.sort(key=lambda neighbor: neighbor.score, reverse=True)
    return scored[:limit]


def boundaries() -> list[BoundaryPoint]:
    points: list[BoundaryPoint] = []
    for left, right in pairwise(CHUNKS):
        score = cosine(left.id, right.id)
        points.append(
            BoundaryPoint(
                left_chunk_id=left.id,
                right_chunk_id=right.id,
                score=score,
                is_boundary=score < SPLIT_THRESHOLD,
            )
        )
    return points


_STAGE_SUMMARY: dict[JobStage, tuple[str, str | None, dict[str, object]]] = {
    JobStage.REGISTER: ("SHA-256 hesaplandı, yeni sürüm açıldı.", None, {"bytes": 13_002_342}),
    JobStage.RENDER: ("48 sayfa 200 DPI PNG olarak render edildi.", "pymupdf-1.24", {"pages": 48, "dpi": 200}),
    JobStage.EXTRACT: ("Docling yapısal JSON + kanonik Markdown üretti.", "docling-2.19", {"blocks": 312, "headings": 9}),
    JobStage.QUALITY: ("6 sayfa kalite kapısına takıldı.", None, {"empty": 0, "short": 2, "scanned": 1, "table_heavy": 3}),
    JobStage.VISION: ("Yalnızca 6 sayfa görsel modele gitti.", "gemini-2.5-flash", {"pages": 6, "derived": True}),
    JobStage.NORMALIZE: ("Başlık seviyeleri ve tablo kaçışları onarıldı.", None, {"fixes": 27}),
    JobStage.CHUNK: ("Başlık öncelikli bölme; 3 bölümde token bazlı fallback.", None, {"fallback": 3, "overlap": 80}),
    JobStage.ENRICH: ("Her chunk'a başlık yolu ve devralınan metadata eklendi.", None, {"chunks": 44}),
    JobStage.EMBED: ("Gömme üretildi, Qdrant ve Postgres FTS güncellendi.", "bge-m3", {"dim": 1024, "vectors": 44}),
    JobStage.PUBLISH: ("Manifest yazıldı, sürüm done olarak işaretlendi.", None, {"manifest": "manifest.json"}),
}

_DURATIONS_MS = [400, 38_000, 112_000, 2_100, 18_200, 1_900, 6_400, 800, 21_000, 300]


def _stages(pattern: list[StageStatus]) -> list[StageRun]:
    runs: list[StageRun] = []
    for index, stage in enumerate(STAGE_ORDER):
        status = pattern[index]
        summary, provider, attributes = _STAGE_SUMMARY[stage]
        runs.append(
            StageRun(
                stage=stage,
                status=status,
                duration_ms=_DURATIONS_MS[index] if status in {StageStatus.DONE, StageStatus.RUNNING} else None,
                summary=summary if status in {StageStatus.DONE, StageStatus.RUNNING} else None,
                provider=provider,
                attributes=attributes if status is StageStatus.DONE else {},
                attempt=1 if status is not StageStatus.PENDING else 0,
            )
        )
    return runs


_ALL_DONE = [StageStatus.DONE] * 10

JOBS: list[Job] = [
    Job(
        id="job_9a12",
        document_id=DOC,
        document_version_id=V2,
        workspace_id=WS,
        status=JobStatus.DONE,
        stages=_stages(_ALL_DONE),
        queued_at=_at(30, 14, 1),
        started_at=_at(30, 14, 1),
        finished_at=_at(30, 14, 6),
        duration_ms=252_000,
        correlation_id="cid_5f21",
    ),
    Job(
        id="job_9a15",
        document_id="doc_kk41",
        document_version_id="dver_kk41_1",
        workspace_id=WS,
        status=JobStatus.RUNNING,
        stages=_stages([StageStatus.DONE] * 6 + [StageStatus.RUNNING] + [StageStatus.PENDING] * 3),
        queued_at=_at(31, 10, 55),
        started_at=_at(31, 10, 56),
        duration_ms=151_000,
        correlation_id="cid_77aa",
    ),
    Job(
        id="job_9a11",
        document_id="doc_pq77",
        document_version_id="dver_pq77_1",
        workspace_id=WS,
        status=JobStatus.PARTIAL,
        stages=_stages(_ALL_DONE),
        page_failures=[
            PageFailure(
                page_number=3,
                stage=JobStage.EXTRACT,
                reason="Metin katmanı boş (taranmış sayfa)",
                resolution="Görsel model ile okundu; içerik türetilmiş olarak işaretlendi.",
            ),
            PageFailure(
                page_number=5,
                stage=JobStage.VISION,
                reason="Sağlayıcı zaman aşımı (30 sn)",
                resolution=None,
            ),
        ],
        queued_at=_at(29, 16, 38),
        started_at=_at(29, 16, 38),
        finished_at=_at(29, 16, 41),
        duration_ms=184_000,
    ),
    Job(
        id="job_9a03",
        document_id="doc_zz01",
        document_version_id="dver_zz01_1",
        workspace_id=WS,
        status=JobStatus.FAILED,
        stages=_stages([StageStatus.DONE, StageStatus.DONE, StageStatus.FAILED] + [StageStatus.PENDING] * 7),
        queued_at=_at(27, 18, 3),
        started_at=_at(27, 18, 3),
        finished_at=_at(27, 18, 3),
        duration_ms=11_000,
    ),
]

DIFF = VersionDiff(
    base_version_id=V1,
    head_version_id=V2,
    page_delta=0,
    chunk_delta=3,
    table_delta=2,
    asset_delta=2,
    entries=[
        DiffEntry(change="added", target_id="chk_08", description="Grafik 2.3 chunk'ı eklendi."),
        DiffEntry(change="added", target_id="tbl_02", description="Sayfa 6'daki tablo yeni parser sürümünde algılandı."),
        DiffEntry(change="added", target_id="tbl_03", description="Sayfa 8'deki tablo algılandı."),
        DiffEntry(change="added", target_id="ast_04", description="Taranmış ek sayfa görsel olarak kaydedildi."),
        DiffEntry(change="modified", target_id="chk_06", description="Başlık yolu düzeltildi."),
        DiffEntry(change="modified", target_id="chk_03", description="Token sayısı 168 -> 142; chunk yeniden bölündü."),
        DiffEntry(change="removed", target_id="chk_39", description="Boş sayfa chunk'ı kaldırıldı."),
    ],
)

PROVIDERS: list[ProviderHealth] = [
    ProviderHealth(interface="DocumentParser", implementation="docling-2.19", healthy=True, location="local", note="birincil parser"),
    ProviderHealth(interface="PageRenderer", implementation="pymupdf-1.24", healthy=True, location="local", note="200 DPI PNG"),
    ProviderHealth(interface="VisionProvider", implementation="gemini-2.5-flash", healthy=True, location="hosted", note="hosted kalite profili"),
    ProviderHealth(interface="VisionProvider", implementation="qwen2.5-vl-3b-instruct", healthy=False, location="local", note="GPU kuyruğu dolu"),
    ProviderHealth(interface="EmbeddingProvider", implementation="bge-m3", healthy=True, location="local", note="1024 boyut"),
    ProviderHealth(interface="VectorIndex", implementation="qdrant-1.12", healthy=True, location="docker", note="collection: docgrain_chunks"),
    ProviderHealth(interface="KeywordIndex", implementation="postgresql-fts", healthy=True, location="docker", note="turkish config"),
    ProviderHealth(interface="ObjectStorage", implementation="minio", healthy=True, location="docker", note="bucket: docgrain"),
]
