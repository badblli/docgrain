"use client";

import { useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Screen = "documents" | "jobs" | "providers" | "contract" | "detail";
type DetailTab = "pipeline" | "pages" | "chunks" | "assets" | "versions";
type DocumentRow = {
  id: string;
  versionId?: string;
  jobId?: string;
  title: string;
  file: string;
  type: string;
  status: string;
  version: string;
  pages: number;
  chunks: number;
  updated: string;
  versionCount: number;
  tables: number;
  assets: number;
};
type Stage = {
  stage: string;
  status: string;
  summary?: string;
  provider?: string;
  duration_ms?: number;
  attributes?: Record<string, unknown>;
  error?: string;
};
type Job = {
  id: string;
  document_id: string;
  document_version_id: string;
  status: string;
  stages: Stage[];
  duration_ms?: number;
};
type Provider = {
  interface: string;
  implementation: string;
  healthy: boolean;
  location: string;
  note?: string;
};
type Page = {
  id: string;
  page_number: number;
  render_uri: string;
  parser: string;
  confidence: number;
  quality_flags: string[];
  derived_content: boolean;
};
type Chunk = {
  id: string;
  text: string;
  embedding_text: string;
  heading_path: string[];
  page_numbers: number[];
  token_count: number;
  table_ids: string[];
  asset_ids: string[];
  access_scope: string;
  split_strategy: string;
  derived: boolean;
  metadata?: Record<string, unknown>;
};
type Neighbor = { chunk_id: string; score: number };
type TableArtifact = {
  id: string;
  page_number: number;
  title: string;
  row_count: number;
  column_count: number;
  confidence: number;
  header: string[];
  rows: string[][];
};
type Asset = {
  id: string;
  page_number: number;
  caption?: string;
  caption_is_derived: boolean;
  mime_type: string;
  width?: number;
  height?: number;
  byte_size?: number;
  sha256?: string;
};
type Version = {
  id: string;
  revision: number;
  page_count: number;
  chunk_count: number;
  table_count: number;
  asset_count: number;
  parser?: string;
  vision_provider?: string;
  status: string;
  created_at: string;
};

const demoDocs: DocumentRow[] = [
  {
    id: "doc_7fk2",
    versionId: "dver_2",
    jobId: "job_9a12",
    title: "Finansal İstikrar Raporu 2025-II",
    file: "fsr-2025-2.pdf",
    type: "PDF",
    status: "done",
    version: "v2",
    pages: 48,
    chunks: 44,
    updated: "30 Ağu 2025, 14:06",
    versionCount: 2,
    tables: 3,
    assets: 4,
  },
  {
    id: "doc_luwi",
    title: "Luwi Müşteri Sözleşmesi",
    file: "sozlesme-v3.docx",
    type: "DOCX",
    status: "done",
    version: "v1",
    pages: 12,
    chunks: 19,
    updated: "30 Ağu 2025, 11:22",
    versionCount: 1,
    tables: 0,
    assets: 0,
  },
  {
    id: "doc_kk41",
    title: "Ürün Kataloğu 2026",
    file: "katalog-2026.pdf",
    type: "PDF",
    status: "running",
    version: "v1",
    pages: 132,
    chunks: 0,
    updated: "31 Ağu 2025, 10:58",
    versionCount: 1,
    tables: 0,
    assets: 0,
  },
  {
    id: "doc_pq77",
    title: "Saha Denetim Formu (taranmış)",
    file: "denetim-2025-08.pdf",
    type: "PDF",
    status: "partial",
    version: "v1",
    pages: 6,
    chunks: 7,
    updated: "29 Ağu 2025, 16:41",
    versionCount: 1,
    tables: 0,
    assets: 0,
  },
  {
    id: "doc_xlsx",
    title: "Q3 Bütçe Tabloları",
    file: "q3-butce.xlsx",
    type: "XLSX",
    status: "done",
    version: "v2",
    pages: 4,
    chunks: 11,
    updated: "28 Ağu 2025, 09:15",
    versionCount: 2,
    tables: 3,
    assets: 0,
  },
  {
    id: "doc_zz01",
    title: "Bozuk Tarama",
    file: "bozuk-dosya.pdf",
    type: "PDF",
    status: "failed",
    version: "—",
    pages: 0,
    chunks: 0,
    updated: "27 Ağu 2025, 18:03",
    versionCount: 0,
    tables: 0,
    assets: 0,
  },
];
const demoJobs: Job[] = [
  {
    id: "job_9a12",
    document_id: "doc_7fk2",
    document_version_id: "dver_2",
    status: "done",
    duration_ms: 252000,
    stages: [],
  },
  {
    id: "job_9a08",
    document_id: "doc_luwi",
    document_version_id: "dver_luwi",
    status: "done",
    duration_ms: 48000,
    stages: [],
  },
  {
    id: "job_9a15",
    document_id: "doc_kk41",
    document_version_id: "dver_kk41_1",
    status: "running",
    duration_ms: 151000,
    stages: [],
  },
  {
    id: "job_9a11",
    document_id: "doc_pq77",
    document_version_id: "dver_pq77_1",
    status: "partial",
    duration_ms: 184000,
    stages: [],
  },
  {
    id: "job_9a06",
    document_id: "doc_xlsx",
    document_version_id: "dver_xlsx",
    status: "done",
    duration_ms: 22000,
    stages: [],
  },
  {
    id: "job_9a03",
    document_id: "doc_zz01",
    document_version_id: "dver_zz01_1",
    status: "failed",
    duration_ms: 11000,
    stages: [],
  },
];
const stageMeta: Record<string, { name: string; via: string }> = {
  register: { name: "Kayıt", via: "POST /v1/documents" },
  render: { name: "Sayfa render", via: "PyMuPDF → PNG" },
  extract: { name: "Çıkarım", via: "Docling" },
  quality: { name: "Kalite kapısı", via: "heuristics" },
  vision: { name: "Görsel model", via: "Gemini / Qwen2.5-VL" },
  normalize: { name: "Normalize", via: "markdown repair" },
  chunk: { name: "Chunk’lama", via: "heading-first + LangChain" },
  enrich: { name: "Zenginleştirme", via: "context header" },
  embed: { name: "Gömme + indeks", via: "embeddings → Qdrant" },
  publish: { name: "Yayın", via: "manifest" },
};
const demoChunks: Chunk[] = [
  [
    "chk_01",
    ["Finansal İstikrar Raporu", "Yönetici Özeti"],
    [1, 2],
    118,
    [],
    [],
    "Bu raporda finansal istikrarı etkileyen makrofinansal gelişmeler değerlendirilmektedir.",
  ],
  [
    "chk_02",
    ["Finansal İstikrar Raporu", "Yönetici Özeti", "Temel bulgular"],
    [2],
    96,
    [],
    [],
    "Takipteki alacak oranındaki artış ılımlıdır, karşılık oranları yüksektir.",
  ],
  [
    "chk_03",
    ["Finansal İstikrar Raporu", "1. Makrofinansal Görünüm"],
    [3],
    142,
    [],
    [],
    "Küresel finansal koşullar 2025 yılının ikinci yarısında bir miktar gevşemiştir.",
  ],
  [
    "chk_04",
    [
      "Finansal İstikrar Raporu",
      "1. Makrofinansal Görünüm",
      "1.1 Küresel gelişmeler",
    ],
    [3],
    131,
    [],
    [],
    "Uzun vadeli tahvil getirilerindeki oynaklık yüksek seyretmeye devam etmektedir.",
  ],
  [
    "chk_05",
    [
      "Finansal İstikrar Raporu",
      "1. Makrofinansal Görünüm",
      "1.2 Yurt içi talep",
    ],
    [3, 4],
    127,
    [],
    [],
    "Cari işlemler dengesindeki iyileşme dışsal şoklara karşı tamponları güçlendirmiştir.",
  ],
  [
    "chk_06",
    ["Finansal İstikrar Raporu", "2. Bankacılık Sektörü", "2.1 Aktif kalitesi"],
    [4],
    158,
    ["tbl_01"],
    [],
    "Takipteki alacak oranı sektör genelinde ılımlı bir artış göstermiştir. Karşılık oranlarının yüksek seyri, olası zararların büyük ölçüde önden karşılandığına işaret etmektedir.",
  ],
  [
    "chk_07",
    ["Finansal İstikrar Raporu", "2. Bankacılık Sektörü", "2.1 Aktif kalitesi"],
    [4, 5],
    149,
    ["tbl_01"],
    ["ast_01"],
    "Kur etkisinden arındırılmış yıllık kredi büyümesi yavaşlamıştır.",
  ],
  [
    "chk_08",
    ["Finansal İstikrar Raporu", "2. Bankacılık Sektörü", "Grafik 2.3"],
    [5],
    88,
    [],
    ["ast_01", "ast_02"],
    "Grafik 2.3, ticari ve tüketici kredi büyümesini zaman serisi olarak göstermektedir.",
  ],
  [
    "chk_09",
    ["Finansal İstikrar Raporu", "3. Hanehalkı Borçluluğu"],
    [6],
    136,
    ["tbl_02"],
    [],
    "Hanehalkı yükümlülüklerinin harcanabilir gelire oranı düşük seviyesini korumaktadır.",
  ],
  [
    "chk_10",
    ["Finansal İstikrar Raporu", "Ek A. Yöntem Notu"],
    [7, 8],
    104,
    ["tbl_03"],
    ["ast_04"],
    "Örneklem 2015-2025 dönemi için mevduat ve katılım bankalarını kapsamaktadır.",
  ],
].map((x: any) => ({
  id: x[0],
  heading_path: x[1],
  page_numbers: x[2],
  token_count: x[3],
  table_ids: x[4],
  asset_ids: x[5],
  text: x[6],
  embedding_text: `${x[1].join(" > ")}\n\n${x[6]}`,
  access_scope: "workspace",
  split_strategy: x[3] > 150 ? "token_fallback" : "heading",
  derived: x[0] === "chk_08",
  metadata: { overlap_tokens: x[3] > 150 ? 80 : 0 },
}));
const demoTables: TableArtifact[] = [
  {
    id: "tbl_01",
    page_number: 4,
    title: "Tablo 2.1 — Aktif kalitesi göstergeleri",
    row_count: 4,
    column_count: 4,
    confidence: 0.94,
    header: ["Dönem", "TGA oranı (%)", "Karşılık (%)", "Yakın izleme (%)"],
    rows: [
      ["2023-IV", "1,62", "82,4", "3,91"],
      ["2024-II", "1,74", "80,9", "4,15"],
      ["2024-IV", "1,88", "79,3", "4,52"],
      ["2025-II", "2,07", "77,8", "4,88"],
    ],
  },
  {
    id: "tbl_02",
    page_number: 6,
    title: "Tablo 3.1 — Hanehalkı yükümlülükleri",
    row_count: 3,
    column_count: 3,
    confidence: 0.87,
    header: ["Kalem", "2024", "2025"],
    rows: [
      ["Konut kredisi", "1.284", "1.512"],
      ["İhtiyaç kredisi", "2.031", "2.388"],
      ["Kredi kartı", "1.907", "2.640"],
    ],
  },
  {
    id: "tbl_03",
    page_number: 8,
    title: "Tablo A.1 — Veri kaynakları",
    row_count: 3,
    column_count: 2,
    confidence: 0.79,
    header: ["Seri", "Kaynak"],
    rows: [
      ["TGA oranı", "BDDK"],
      ["Kredi büyümesi", "TCMB EVDS"],
      ["Hanehalkı geliri", "TÜİK"],
    ],
  },
];
const demoAssets: Asset[] = [
  {
    id: "ast_01",
    page_number: 5,
    caption:
      "Yıllık kredi büyümesi: ticari ve tüketici kredileri, kur etkisinden arındırılmış.",
    caption_is_derived: true,
    mime_type: "image/png",
    width: 1240,
    height: 720,
    byte_size: 188416,
    sha256: "9c4f…a71b",
  },
  {
    id: "ast_02",
    page_number: 5,
    caption: "Sektör bazında TGA oranı dağılımı, 2025-II.",
    caption_is_derived: true,
    mime_type: "image/png",
    width: 980,
    height: 640,
    byte_size: 123904,
    sha256: "2ea8…4d10",
  },
  {
    id: "ast_03",
    page_number: 1,
    caption: "Kurum amblemi (kapak).",
    caption_is_derived: false,
    mime_type: "image/png",
    width: 420,
    height: 420,
    byte_size: 22528,
    sha256: "71bc…9f02",
  },
  {
    id: "ast_04",
    page_number: 7,
    caption: "Taranmış ek sayfa; görsel model tarafından okundu.",
    caption_is_derived: true,
    mime_type: "image/png",
    width: 2480,
    height: 3508,
    byte_size: 1468006,
    sha256: "55da…08e7",
  },
];

async function getJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`${API}${path}`);
    if (!r.ok) throw 0;
    return await r.json();
  } catch {
    return fallback;
  }
}
async function getText(path: string): Promise<string> {
  try {
    const response = await fetch(`${API}${path}`);
    return response.ok ? await response.text() : "";
  } catch {
    return "";
  }
}
const duration = (ms = 0) =>
  ms >= 60000
    ? `${Math.floor(ms / 60000)} dk ${String(Math.round((ms % 60000) / 1000)).padStart(2, "0")} sn`
    : `${Math.round(ms / 1000)} sn`;
const statusLabel = (s: string) =>
  ({
    done: "tamamlandı",
    running: "çalışıyor",
    processing: "çalışıyor",
    partial: "kısmi",
    failed: "başarısız",
    queued: "kuyrukta",
    pending: "bekliyor",
    skipped: "atlandı",
  })[s] ?? s;
const pillClass = (s: string) =>
  s === "done"
    ? "p-ok"
    : s === "running" || s === "processing"
      ? "p-run"
      : s === "partial"
        ? "p-warn"
        : s === "failed"
          ? "p-err"
          : "p-idle";
function Icon({ name }: { name: string }) {
  const p: Record<string, React.ReactNode> = {
    doc: (
      <>
        <path d="M6 2.75h8l4 4V21.25H6z" />
        <path d="M14 2.75v4h4M9 11h6M9 15h6" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 7.5V12l3 2" />
      </>
    ),
    grid: (
      <>
        <rect x="4" y="4" width="6" height="6" />
        <rect x="14" y="4" width="6" height="6" />
        <rect x="4" y="14" width="6" height="6" />
        <rect x="14" y="14" width="6" height="6" />
      </>
    ),
    book: (
      <>
        <path d="M5 4h6a3 3 0 0 1 3 3v13H8a3 3 0 0 0-3 1z" />
        <path d="M19 4h-2a3 3 0 0 0-3 3v13h3a3 3 0 0 1 2 1z" />
      </>
    ),
    upload: (
      <>
        <path d="M12 16V4M7.5 8.5 12 4l4.5 4.5" />
        <path d="M4 14v6h16v-6" />
      </>
    ),
  };
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {p[name]}
    </svg>
  );
}
function Status({ status }: { status: string }) {
  return (
    <span className={`pill ${pillClass(status)}`}>
      <i className="dot" />
      {statusLabel(status)}
    </span>
  );
}
function Ep({ children }: { children: React.ReactNode }) {
  return <code className="ep">{children}</code>;
}
function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="wrap">
      <section className="card emptyArtifact">
        <span>◇</span>
        <h2>{title}</h2>
        <p>{text}</p>
      </section>
    </div>
  );
}
function Sidebar({
  screen,
  nav,
  docs,
  jobs,
}: {
  screen: Screen;
  nav: (s: Screen) => void;
  docs: number;
  jobs: number;
}) {
  return (
    <aside className="rail">
      <button className="brand" onClick={() => nav("documents")}>
        <svg className="mark" viewBox="0 0 28 28" fill="none">
          <path d="M5 3.5h12l5 5V24.5H5z" stroke="#56534D" strokeWidth="1.5" />
          <path d="M17 3.5v5h5M8.5 12h8M8.5 16h7" stroke="#787774" />
          <circle cx="20.5" cy="20.5" r="4" fill="#EEEEEC" stroke="#787774" />
          <path d="m18.8 20.6 1.1 1.1 2.1-2.3" stroke="#37352F" />
        </svg>
        <span>
          <b>Docgrain</b>
          <small>konsol</small>
        </span>
      </button>
      <div className="navlbl">Çalışma alanı</div>
      <button
        className="nav"
        aria-current={screen === "documents" || screen === "detail"}
        onClick={() => nav("documents")}
      >
        <Icon name="doc" />
        Dokümanlar<em>{docs}</em>
      </button>
      <button
        className="nav"
        aria-current={screen === "jobs"}
        onClick={() => nav("jobs")}
      >
        <Icon name="clock" />
        İşler<em>{jobs}</em>
      </button>
      <button
        className="nav"
        aria-current={screen === "providers"}
        onClick={() => nav("providers")}
      >
        <Icon name="grid" />
        Sağlayıcılar
      </button>
      <div className="navlbl">Referans</div>
      <button
        className="nav"
        aria-current={screen === "contract"}
        onClick={() => nav("contract")}
      >
        <Icon name="book" />
        Veri sözleşmesi
      </button>
      <div className="railfoot">
        Prototip · canlı API
        <br />
        Ekranlar <code>/v1</code> sözleşmesine göre çizildi; her başlıktaki mavi
        rozet o ekranı besleyen uç noktadır.
      </div>
    </aside>
  );
}
function Head({
  section = "Çalışma alanı",
  title,
  sub,
  endpoint,
  children,
}: {
  section?: string;
  title: string;
  sub: string;
  endpoint: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="head">
      <div className="crumb">
        <span>{section}</span>
        <b>›</b>
        <span>{title}</span>
      </div>
      <div className="h1row">
        <div>
          <h1>{title}</h1>
          <p className="sub">{sub}</p>
        </div>
        <div className="headact">
          {children}
          <Ep>{endpoint}</Ep>
        </div>
      </div>
    </header>
  );
}

function Documents({
  docs,
  open,
  toast,
}: {
  docs: DocumentRow[];
  open: (d: DocumentRow) => void;
  toast: (s: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <Head
        title="Dokümanlar"
        sub="Yüklenen her dosya bir doküman, her yeni içerik özeti (hash) o dokümanın yeni bir sürümü olur. Eski sürümler asla değişmez."
        endpoint="GET /v1/documents"
      />
      <div className="wrap">
        <section className="drop">
          <div className="ico">
            <Icon name="upload" />
          </div>
          <div>
            <h3>Doküman yükle veya bir kaynak kaydet</h3>
            <p>
              PDF, DOCX, PPTX, XLSX, HTML. Dosya nesne depolamaya olduğu gibi
              yazılır, hash’i alınır ve dayanıklı bir iş kuyruğa girer — API
              isteği hiçbir zaman çıkarımı kendi içinde çalıştırmaz.
            </p>
          </div>
          <input
            ref={input}
            type="file"
            hidden
            accept=".pdf,.docx,.pptx,.xlsx,.html"
            onChange={(e) =>
              e.target.files?.[0] &&
              toast(`${e.target.files[0].name} seçildi · yükleme akışı hazır`)
            }
          />
          <button
            className="btn pri dropAction"
            onClick={() => input.current?.click()}
          >
            Dosya seç
          </button>
        </section>
        <section className="card">
          <header>
            <h2>Tüm dokümanlar</h2>
            <p className="note">
              Satıra tıkla → sürüm, pipeline ve çıkarılan içerik.
            </p>
            <span className="sp">
              <Ep>GET /v1/documents?limit=50</Ep>
            </span>
          </header>
          <div className="scrollx">
            <table className="grid docs">
              <thead>
                <tr>
                  <th>Doküman</th>
                  <th>Durum</th>
                  <th>Sürüm</th>
                  <th>Sayfa</th>
                  <th>Chunk</th>
                  <th>Son işlem</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id} className="click" onClick={() => open(d)}>
                    <td>
                      <span className="fname">
                        <span className="ftype">{d.type}</span>
                        <span>
                          {d.title} <small>{d.file}</small>
                        </span>
                      </span>
                    </td>
                    <td>
                      <Status status={d.status} />
                    </td>
                    <td>{d.version}</td>
                    <td>{d.pages || "—"}</td>
                    <td>{d.chunks || "—"}</td>
                    <td className="mono muted">{d.updated}</td>
                    <td>
                      <button
                        className="btn sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          open(d);
                        }}
                      >
                        Aç
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}
function Jobs({
  jobs,
  docs,
  retry,
}: {
  jobs: Job[];
  docs: DocumentRow[];
  retry: (j: Job) => void;
}) {
  const count = (s: string) => jobs.filter((j) => j.status === s).length;
  const current = (j: Job) => {
    const x = [...j.stages]
      .reverse()
      .find((s) => ["running", "failed", "done"].includes(s.status));
    return x ? stageMeta[x.stage]?.name : "Yayınlandı";
  };
  return (
    <>
      <Head
        title="İşler"
        sub="Her sürüm için tek bir dayanıklı iş çalışır. İş, worker çökse bile kaldığı aşamadan devam eder."
        endpoint="GET /v1/jobs"
      />
      <div className="wrap">
        <div className="stats">
          {[
            ["Kuyrukta", 0, "bekleyen iş yok", ""],
            ["Çalışan", count("running"), "katalog-2026.pdf", "blue"],
            [
              "Kısmi",
              count("partial"),
              "sayfa düzeyi hata raporu var",
              "amber",
            ],
            ["Başarısız", count("failed"), "yeniden denenebilir", "red"],
            ["24 saat", jobs.length, "toplam iş", ""],
          ].map((x) => (
            <div className="stat" key={String(x[0])}>
              <div className="lb">{x[0]}</div>
              <div className={`vl ${x[3]}`}>{x[1]}</div>
              <div className="sub2">{x[2]}</div>
            </div>
          ))}
        </div>
        <section className="card">
          <header>
            <h2>İş kuyruğu</h2>
            <p className="note">
              Şerit, 10 aşamanın hangisine kadar gelindiğini gösterir.
            </p>
            <span className="sp">
              <Ep>GET /v1/jobs?status=all</Ep>
            </span>
          </header>
          <div className="scrollx">
            <table className="grid jobs">
              <thead>
                <tr>
                  <th>İş</th>
                  <th>Doküman</th>
                  <th>Durum</th>
                  <th>Aşamalar</th>
                  <th>Şu an</th>
                  <th>Süre</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => {
                  const n =
                    j.stages.filter((s) => s.status === "done").length ||
                    (j.status === "done" || j.status === "partial"
                      ? 10
                      : j.status === "running"
                        ? 6
                        : 2);
                  return (
                    <tr key={j.id}>
                      <td className="mono">{j.id}</td>
                      <td>
                        {docs.find((d) => d.id === j.document_id)?.title ??
                          j.document_id}
                      </td>
                      <td>
                        <Status status={j.status} />
                      </td>
                      <td>
                        <div className="miniRail">
                          {Array.from({ length: 10 }, (_, i) => (
                            <i
                              key={i}
                              className={
                                i < n
                                  ? "done"
                                  : i === n && j.status === "running"
                                    ? "run"
                                    : j.status === "failed" && i === n
                                      ? "err"
                                      : ""
                              }
                            />
                          ))}
                        </div>
                      </td>
                      <td>{current(j)}</td>
                      <td className="mono">{duration(j.duration_ms)}</td>
                      <td>
                        {["failed", "partial"].includes(j.status) && (
                          <button className="btn sm" onClick={() => retry(j)}>
                            Yeniden dene
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}
function Providers({ items }: { items: Provider[] }) {
  return (
    <>
      <Head
        title="Sağlayıcılar"
        sub="Parser, görsel model, gömme ve indeks katmanları takılıp çıkarılabilir. Hiçbiri çekirdek veri modeline sızmaz."
        endpoint="GET /v1/providers/health"
      />
      <div className="wrap">
        <div className="explain">
          <b>Sağlayıcılar arayüz üzerinden bağlanır:</b> VisionProvider’ı
          Gemini’den Qwen’e çevirmek pipeline kodunu değiştirmez, yalnızca{" "}
          <code>.env</code> profilini değiştirir. Bu ekran hangi profilin
          çalıştığını ve sağlıklı olup olmadığını gösterir.
        </div>
        <section className="card">
          <header>
            <h2>Bağlı sağlayıcılar</h2>
            <span className="sp">
              <Ep>GET /v1/providers/health</Ep>
            </span>
          </header>
          <table className="grid">
            <thead>
              <tr>
                <th>Arayüz</th>
                <th>Uygulama</th>
                <th>Durum</th>
                <th>Son çalıştırma</th>
                <th>Konum</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p, i) => (
                <tr key={i}>
                  <td className="mono strong">
                    {p.interface}
                    {p.interface === "VisionProvider" && i > 2 ? " (alt)" : ""}
                  </td>
                  <td>{p.implementation}</td>
                  <td>
                    <span className={`pill ${p.healthy ? "p-ok" : "p-warn"}`}>
                      <i className="dot" />
                      {p.healthy ? "hazır" : "uyarı"}
                    </span>
                  </td>
                  <td className="muted">{p.note}</td>
                  <td>
                    <code className="chip">{p.location}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </>
  );
}
const endpoints = [
  [
    "POST /v1/documents",
    "Kaynağı doğrular, hash alır, sürüm açar, iş kuyruğa atar",
    "Dokümanlar → yükleme",
  ],
  ["GET /v1/documents", "Doküman listesi + son sürüm özeti", "Dokümanlar"],
  ["GET /v1/documents/{id}", "Doküman, sürümler, sayaçlar", "Doküman başlığı"],
  ["GET /v1/jobs/{id}", "10 aşamanın durumu, süre, uyarı, hata", "Pipeline"],
  [
    "GET /v1/versions/{id}/pages",
    "Sayfa listesi: render URI, güven, bayraklar",
    "Sayfalar",
  ],
  [
    "GET /v1/versions/{id}/pages/{n}",
    "Tek sayfanın markdown/json/tablo/asset’i",
    "Sayfalar sağ panel",
  ],
  ["GET /v1/versions/{id}/chunks", "Chunk manifesti", "Chunk’lar"],
  [
    "GET /v1/chunks/{id}/neighbors",
    "Cosine komşuları + skorlar",
    "Benzerlik paneli",
  ],
  ["GET /v1/versions/{id}/diff?base=", "İki sürüm arasındaki fark", "Sürümler"],
  [
    "POST /v1/versions/{id}/retry",
    "Aşama bazlı yeniden deneme",
    "Pipeline → hata",
  ],
];
function Contract() {
  return (
    <>
      <Head
        section="Referans"
        title="Veri sözleşmesi"
        sub="Önyüzün tamamı bu şekiller üzerine kuruldu. Backend yazılırken pazarlık konusu olmayan omurga budur."
        endpoint="GET /v1/chunks/{id}"
      />
      <div className="wrap">
        <section className="card">
          <header>
            <h2>Hiyerarşi</h2>
            <p className="note">
              Her ok bir sahiplik ilişkisi; alt kayıt üstü olmadan var olamaz.
            </p>
          </header>
          <pre className="tree">{`Workspace\n  └─ Document              doc_*\n       └─ DocumentVersion   dver_*   ← içerik hash'i değişince yenisi açılır, eskisi asla değişmez\n            ├─ Page         pg_*     ← PNG render + güven skoru + bayraklar\n            │   ├─ Asset    ast_*    ← görsel, bbox, checksum\n            │   ├─ Table    tbl_*    ← json + markdown + html\n            │   └─ Section  sec_*\n            └─ Chunk        chk_*\n                 ├─ Embedding   emb_*\n                 └─ IndexRecord idx_*`}</pre>
        </section>
        <section className="card">
          <header>
            <h2>Chunk sözleşmesi</h2>
            <p className="note">
              Bir chunk en az bu alanları taşımak zorunda; taşımıyorsa
              yayımlanamaz.
            </p>
            <span className="sp">
              <Ep>GET /v1/chunks/chk_06</Ep>
            </span>
          </header>
          <pre className="json">{JSON.stringify(demoChunks[5], null, 2)}</pre>
        </section>
        <section className="card">
          <header>
            <h2>Uç noktalar</h2>
          </header>
          <table className="grid">
            <thead>
              <tr>
                <th>Uç nokta</th>
                <th>Ne yapar</th>
                <th>Hangi ekran</th>
              </tr>
            </thead>
            <tbody>
              {endpoints.map((e) => (
                <tr key={e[0]}>
                  <td>
                    <Ep>{e[0]}</Ep>
                  </td>
                  <td>{e[1]}</td>
                  <td>{e[2]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </>
  );
}

function DetailHead({
  doc,
  tab,
  setTab,
}: {
  doc: DocumentRow;
  tab: DetailTab;
  setTab: (t: DetailTab) => void;
}) {
  const tabs: [DetailTab, string, string][] = [
    ["pipeline", "Pipeline", "10 aşama"],
    ["pages", "Sayfalar", String(doc.pages)],
    ["chunks", "Chunk’lar", String(doc.chunks)],
    ["assets", "Tablo & Görsel", String(doc.tables + doc.assets)],
    ["versions", "Sürümler", String(doc.versionCount)],
  ];
  return (
    <header className="head">
      <div className="crumb">
        <span>Çalışma alanı</span>
        <b>›</b>
        <span>Dokümanlar</span>
        <b>›</b>
        <span>{doc.title}</span>
      </div>
      <div className="h1row">
        <div>
          <h1>{doc.title}</h1>
          <p className="sub mono">
            {doc.file} · {doc.pages} sayfa · sürüm {doc.version}
          </p>
        </div>
        <div className="headact">
          <Status status={doc.status} />
          <Ep>GET /v1/documents/{doc.id}</Ep>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {tabs.map((t) => (
          <button
            className="tab"
            role="tab"
            aria-selected={tab === t[0]}
            key={t[0]}
            onClick={() => setTab(t[0])}
          >
            {t[1]}
            <i>{t[2]}</i>
          </button>
        ))}
      </div>
    </header>
  );
}
function Pipeline({ job }: { job: Job | null }) {
  const stages: Stage[] = job?.stages.length
    ? job.stages
    : Object.keys(stageMeta).map((s) => ({
        stage: s,
        status: "done",
        summary:
          s === "quality"
            ? "6 sayfa kalite kapısına takıldı; görsel modele yönlendirildi."
            : s === "publish"
              ? "Manifest yazıldı, sürüm done olarak işaretlendi."
              : `${stageMeta[s].name} çıktısı nesne depolamaya yazıldı.`,
        duration_ms: 800,
      }));
  return (
    <div className="wrap">
      <section className="card">
        <header>
          <div>
            <h2>İş {job?.id ?? "job_9a12"}</h2>
            <p className="note">
              30 Ağu 2025, 14:06 · {duration(job?.duration_ms ?? 252000)}
            </p>
          </div>
          <span className="sp">
            <Status status={job?.status ?? "done"} />
          </span>
          <Ep>GET /v1/jobs/{job?.id ?? "job_9a12"}</Ep>
        </header>
        <div className="rail10">
          {stages.map((s) => (
            <div
              key={s.stage}
              className={`seg ${s.status === "done" ? "done" : s.status === "running" ? "run" : s.status === "failed" ? "err" : ""}`}
            >
              <div className="bar" />
              <div className="lbl">{stageMeta[s.stage]?.name}</div>
            </div>
          ))}
        </div>
        {stages.map((s, i) => (
          <div
            className={`stage c-${s.status === "done" ? "ok" : s.status === "running" ? "run" : s.status === "failed" ? "err" : "idle"}`}
            key={s.stage}
          >
            <div className="gut">
              <i className="node" />
              <i className="wire" />
            </div>
            <div className="body">
              <div className="top">
                <span className="nm">
                  {i + 1}. {stageMeta[s.stage]?.name}
                </span>
                <span className={`pill ${pillClass(s.status)}`}>
                  {statusLabel(s.status)}
                </span>
                <code className="chip">
                  {s.provider ?? stageMeta[s.stage]?.via}
                </code>
                <span className="dur">
                  {s.duration_ms ? duration(s.duration_ms) : "—"}
                </span>
              </div>
              <p className="out">{s.summary ?? "Bu katman sırada bekliyor."}</p>
              {s.attributes && (
                <div className="det">
                  {Object.entries(s.attributes)
                    .slice(0, 5)
                    .map(([k, v]) => (
                      <code className="chip" key={k}>
                        {k} <b>{String(v)}</b>
                      </code>
                    ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </section>
      <div className="explain">
        <b>Neden 10 ayrı aşama?</b> Her aşama kendi çıktısını nesne depolamaya
        yazar. Worker çökerse iş baştan değil, son tamamlanan aşamadan devam
        eder; bir aşama tek başına yeniden denenebilir.
      </div>
    </div>
  );
}
function PageSheet({
  page = 4,
  small = false,
  src,
}: {
  page?: number;
  small?: boolean;
  src?: string;
}) {
  if (src) {
    return (
      <div className={`paperMock real ${small ? "small" : ""}`}>
        <img src={src} alt={`Sayfa ${page} önizlemesi`} />
      </div>
    );
  }
  return (
    <div className={`paperMock ${small ? "small" : ""}`}>
      <i />
      <i />
      <i />
      <i className="short" />
      {page === 4 && (
        <div className="mockTable">
          <span>tbl_01</span>
          {Array.from({ length: 16 }, (_, i) => (
            <b key={i} />
          ))}
        </div>
      )}
      {page === 5 && (
        <div className="mockChart">
          <b />
          <b />
          <b />
          <b />
          <b />
        </div>
      )}
    </div>
  );
}
function PagesView({
  pages,
  tables,
  chunks,
  markdown,
}: {
  pages: Page[];
  tables: TableArtifact[];
  chunks: Chunk[];
  markdown: string;
}) {
  const [n, setN] = useState(pages[0]?.page_number ?? 1),
    p = pages.find((x) => x.page_number === n),
    table = tables.find((t) => t.page_number === n) ?? tables[0];
  if (!pages.length) {
    return (
      <EmptyState
        title="Sayfa render’ları henüz hazır değil"
        text="Pipeline tamamlandığında gerçek sayfa PNG’leri burada görünecek."
      />
    );
  }
  return (
    <div className="wrap">
      <section className="card viewer">
        <div className="thumbs">
          {pages.slice(0, 18).map((page) => (
            <button
              className="thumb"
              aria-current={n === page.page_number}
              key={page.id}
              onClick={() => setN(page.page_number)}
            >
              <span className="sh">
                <PageSheet page={page.page_number} src={page.render_uri} small />
              </span>
              <span className="n">{page.page_number}</span>
            </button>
          ))}
        </div>
        <div className="stage-pane">
          <div className="flags">
            <span className="pill p-idle">
              <i className="dot" />
              sayfa {n} / {pages.length}
            </span>
            <code className="chip">
              güven <b>{(p?.confidence ?? 0.91).toFixed(2)}</b>
            </code>
            <code className="chip">{p?.parser ?? "docling + gemini"}</code>
            <label className="switch">
              <input type="checkbox" defaultChecked /> kaynak kutuları
            </label>
          </div>
          <PageSheet page={n} src={p?.render_uri} />
          <code className="mono muted">{p?.render_uri}</code>
        </div>
        <div className="extract">
          <div className="minitabs">
            <button className="minitab" aria-selected>
              Markdown
            </button>
            <button className="minitab">JSON</button>
            <button className="minitab">Tablolar</button>
            <button className="minitab">Görseller</button>
          </div>
          <div className="flags">
            {(p?.quality_flags ?? []).map((f) => (
              <span className="pill p-warn" key={f}>
                <i className="dot" />
                {f.replace("-", " ")}
              </span>
            ))}
          </div>
          <div className="md">
            {markdown ? (
              <pre className="realMarkdown">{markdown}</pre>
            ) : (
              <p>Bu sürüm için kanonik Markdown henüz yazılmadı.</p>
            )}
            {table && (
              <table>
                <thead>
                  <tr>
                    {table.header.map((h) => (
                      <th key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((r, i) => (
                    <tr key={i}>
                      {r.map((c, j) => (
                        <td key={j}>{c}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="sourceChunks">
            <span>Bu sayfadan üretilen chunk’lar</span>
            <div>
              {chunks
                .filter((c) => c.page_numbers.includes(n))
                .map((c) => (
                  <button className="chip" key={c.id}>
                    {c.id} · {c.token_count} tok
                  </button>
                ))}
            </div>
          </div>
        </div>
      </section>
      <div className="explain">
        <b>Sol taraf her zaman kaynaktır.</b> Sağdaki metin o sayfadan çıkarılan
        içeriğin kendisidir; mor işaretli bloklar ise türetilmiş içeriktir.
      </div>
    </div>
  );
}
function Similarity() {
  const vals = [0.853, 0.569, 0.843, 0.793, 0.594, 0.88, 0.829, 0.506, 0.454];
  return (
    <section className="card">
      <header>
        <h2>Bölme sınırı doğrulaması</h2>
        <p className="note">
          Ardışık chunk çiftleri arasındaki cosine benzerliği.
        </p>
        <span className="sp">
          <Ep>GET /v1/versions/dver_2/chunks/boundaries</Ep>
        </span>
      </header>
      <div className="chart">
        <div className="threshold">eşik 0.55</div>
        {vals.map((v, i) => (
          <div className="chartCol" key={i}>
            <i
              className={v < 0.55 ? "low" : ""}
              style={{ height: `${v * 130}px` }}
            />
            <small>
              {i + 1}|{i + 2}
            </small>
          </div>
        ))}
      </div>
    </section>
  );
}
function ChunkView({ chunks }: { chunks: Chunk[] }) {
  const [selected, setSelected] = useState(
      chunks.find((c) => c.id === "chk_06") ?? chunks[0],
    ),
    [neighbors, setNeighbors] = useState<Neighbor[]>([]);
  useEffect(() => {
    if (!selected && chunks[0]) {
      setSelected(chunks[0]);
      return;
    }
    if (selected)
      getJson(`/v1/chunks/${selected.id}/neighbors?limit=5`, []).then((x) =>
        setNeighbors(x),
      );
  }, [chunks, selected]);
  if (!selected)
    return (
      <EmptyState
        title="Chunk üretimi bu sürümde çalıştırılmadı"
        text="Gerçek pipeline’da chunk aşaması etkinleştirildiğinde indekslenen parçalar burada görünecek."
      />
    );
  return (
    <div className="wrap">
      <section className="card chunkgrid">
        <div className="chunklist">
          {chunks.map((c) => (
            <button
              className="crow"
              aria-current={selected.id === c.id}
              key={c.id}
              onClick={() => setSelected(c)}
            >
              <span className="id">{c.id}</span>
              <div className="hp">{c.heading_path.at(-1)}</div>
              <div className="mt">
                <span>s.{c.page_numbers.join("–")}</span>
                <span>{c.token_count} tok</span>
                {c.table_ids.length > 0 && (
                  <span>{c.table_ids.length} tablo</span>
                )}
                {c.asset_ids.length > 0 && (
                  <span>{c.asset_ids.length} görsel</span>
                )}
              </div>
            </button>
          ))}
        </div>
        <div className="chunkdet">
          <div className="chunkTitle">
            <Ep>{selected.id}</Ep>
            <span>… › {selected.heading_path.slice(-2).join(" › ")}</span>
            <span className="sp">
              <Ep>GET /v1/chunks/{selected.id}</Ep>
            </span>
          </div>
          <div>
            <label className="fieldLabel">text — indekslenen ham metin</label>
            <div className="ctext">{selected.text}</div>
          </div>
          <div>
            <label className="fieldLabel">
              embedding_text — gömmeye giden metin
            </label>
            <div className="embtext">
              <u>{selected.heading_path.join(" > ")}</u>
              <br />
              <br />
              {selected.text}
            </div>
            <p className="helper">
              Başlık yolu metnin başına eklenir; böylece bağlamsız bir cümle
              bile hangi bölüme ait olduğunu vektör uzayında taşır.
            </p>
          </div>
          <div className="chunkBottom">
            <dl className="kv">
              <dt>pages</dt>
              <dd>
                [{selected.page_numbers.join(", ")}]{" "}
                <button className="btn sm">sayfayı aç →</button>
              </dd>
              <dt>token</dt>
              <dd>{selected.token_count}</dd>
              <dt>strateji</dt>
              <dd>
                {selected.split_strategy.replace(
                  "token_fallback",
                  "heading + token fallback (overlap 80)",
                )}
              </dd>
              <dt>table_ids</dt>
              <dd>[{selected.table_ids.join(", ") || "—"}]</dd>
              <dt>asset_ids</dt>
              <dd>[{selected.asset_ids.join(", ") || "—"}]</dd>
              <dt>access_scope</dt>
              <dd>{selected.access_scope}</dd>
            </dl>
            <div>
              <label className="fieldLabel">En yakın komşular (cosine)</label>
              <div className="nb">
                {neighbors.map((n) => (
                  <div className="nbRow" key={n.chunk_id}>
                    <button
                      onClick={() => {
                        const c = chunks.find((x) => x.id === n.chunk_id);
                        if (c) setSelected(c);
                      }}
                    >
                      {n.chunk_id}
                    </button>
                    <div className="bar">
                      <i style={{ width: `${n.score * 100}%` }} />
                    </div>
                    <span className="sc">{n.score.toFixed(3)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
      <Similarity />
      <div className="explain">
        <b>Bu grafik ne söylüyor?</b> Yüksek nokta, iki komşu chunk’ın aynı
        konudan bahsettiğini; eşiğin altına düşen kırmızı nokta ise konunun
        gerçekten değiştiğini gösterir.
      </div>
    </div>
  );
}
function AssetsView({
  tables,
  assets,
}: {
  tables: TableArtifact[];
  assets: Asset[];
}) {
  if (!tables.length && !assets.length) {
    return (
      <EmptyState
        title="Tablo veya bağımsız görsel üretilmedi"
        text="Bu sürümde Docling çıktısı ve sayfa render’ları mevcut; ayrıştırılmış tablo/görsel aşamaları henüz etkin değil."
      />
    );
  }
  return (
    <div className="wrap">
      <section className="card">
        <header>
          <h2>Tablolar</h2>
          <p className="note">
            Tablo, metne düzleştirilmez; yapısal JSON olarak saklanır ve
            chunk’lara table_ids ile bağlanır.
          </p>
          <span className="sp">
            <Ep>GET /v1/versions/dver_2/tables</Ep>
          </span>
        </header>
        <div className="tableStack">
          {tables.map((t) => (
            <div className="dataTable" key={t.id}>
              <div className="dataTitle">
                <b>{t.title}</b>
                <button className="chip">sayfa {t.page_number} →</button>
                <code className="chip">{t.id}</code>
                <code className="chip">
                  {t.row_count}×{t.column_count}
                </code>
                <code className="chip">
                  güven <b>{t.confidence}</b>
                </code>
              </div>
              <table className="grid">
                <thead>
                  <tr>
                    {t.header.map((h) => (
                      <th key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {t.rows.map((r, i) => (
                    <tr key={i}>
                      {r.map((c, j) => (
                        <td key={j}>{c}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </section>
      <section className="card">
        <header>
          <h2>Görseller</h2>
          <p className="note">
            Her görsel sayfa numarası, bbox, MIME, checksum ve depolama
            URI’siyle saklanır. Mor rozet, açıklamanın model tarafından
            üretildiğini söyler.
          </p>
          <span className="sp">
            <Ep>GET /v1/versions/dver_2/assets</Ep>
          </span>
        </header>
        <div className="gal pad">
          {assets.map((a, i) => (
            <button className="gcard" key={a.id}>
              <div className={`frame assetArt a${i + 1}`}>
                <div>
                  {i < 2 ? (
                    <>
                      <i />
                      <i />
                      <i />
                      <i />
                    </>
                  ) : (
                    <PageSheet page={a.page_number} small />
                  )}
                </div>
              </div>
              <div className="meta">
                <div className="flags">
                  <Ep>{a.id}</Ep>
                  <code className="chip">s.{a.page_number}</code>
                  {a.caption_is_derived && (
                    <span className="pill p-der">türetilmiş</span>
                  )}
                </div>
                <span className="cap">{a.caption}</span>
                <span className="sm">
                  {a.mime_type} · {a.width}×{a.height} ·{" "}
                  {a.byte_size ? Math.round(a.byte_size / 1024) : 0} KB · sha{" "}
                  {a.sha256?.slice(0, 9)}
                </span>
              </div>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
function VersionBox({ v, current }: { v: Version; current?: boolean }) {
  return (
    <div className="vbox">
      <h4>
        {v.id}{" "}
        {current && (
          <span className="pill p-ok">
            <i className="dot" />
            güncel
          </span>
        )}
      </h4>
      <div className="when">
        {new Date(v.created_at).toLocaleDateString("tr-TR", {
          day: "2-digit",
          month: "short",
          year: "numeric",
        })}{" "}
        · {v.parser}
        {v.vision_provider ? ` · ${v.vision_provider}` : " · görsel model yok"}
      </div>
      <dl className="kv">
        <dt>sayfa</dt>
        <dd>{v.page_count}</dd>
        <dt>chunk</dt>
        <dd>{v.chunk_count}</dd>
        <dt>tablo</dt>
        <dd>{v.table_count}</dd>
        <dt>görsel</dt>
        <dd>{v.asset_count}</dd>
        <dt>durum</dt>
        <dd>{v.status}</dd>
      </dl>
    </div>
  );
}
function VersionsView({ versions }: { versions: Version[] }) {
  if (!versions.length) {
    return (
      <EmptyState
        title="Sürüm bilgisi bulunamadı"
        text="Doküman kaydı yayımlandığında sürüm özeti burada görünecek."
      />
    );
  }
  const vs = [...versions].sort((a, b) => a.revision - b.revision);
  if (vs.length === 1) {
    return (
      <div className="wrap">
        <div className="singleVersion">
          <VersionBox v={vs[0]} current />
        </div>
        <div className="explain">
          <b>İlk sürüm.</b> Aynı dokümanın içeriği değişerek yeniden
          yüklendiğinde yeni sürüm ve gerçek farklar burada yan yana gösterilir.
        </div>
      </div>
    );
  }
  const entries = [
      [
        "+",
        "chk_08 — “Grafik 2.3” chunk’ı eklendi (görsel açıklaması artık chunk üretiyor)",
      ],
      [
        "+",
        "tbl_02, tbl_03 — sayfa 6 ve 8’deki tablolar yeni parser sürümünde algılandı",
      ],
      ["+", "ast_04 — taranmış ek sayfa görsel olarak kaydedildi"],
      ["~", "chk_06 — başlık yolu düzeltildi"],
      ["~", "chk_03 — token sayısı 168 → 142"],
      ["−", "chk_39 — boş sayfa chunk’ı kaldırıldı"],
      ["~", "sayfa 7 — güven 0,12 → 0,41; görsel model devreye girdi"],
    ];
  return (
    <div className="wrap">
      <div className="vcmp">
        <VersionBox v={vs[0]} />
        <div className="arrow">→</div>
        <VersionBox v={vs.at(-1)!} current />
      </div>
      <section className="card">
        <header>
          <h2>Fark</h2>
          <p className="note">
            Sürümler birbirinin üzerine yazılmaz; eski sürüm ve indeksi silinene
            kadar sorgulanabilir kalır.
          </p>
          <span className="sp">
            <Ep>GET /v1/versions/dver_2/diff?base=dver_1</Ep>
          </span>
        </header>
        <div className="dl pad">
          {entries.map((e, i) => (
            <div className="row" key={i}>
              <span
                className={`sign ${e[0] === "+" ? "s-add" : e[0] === "−" ? "s-del" : "s-mod"}`}
              >
                {e[0]}
              </span>
              {e[1]}
            </div>
          ))}
        </div>
      </section>
      <div className="explain">
        <b>Yeniden yükleme neden yeni sürüm açar?</b> Aynı dosyanın içerik
        hash’i değişirse Docgrain eski sayfaları, tabloları ve chunk’ları
        silmez; yenisini yeni sürüm altında oluşturur.
      </div>
    </div>
  );
}
function Detail({
  doc,
  tab,
  setTab,
  job,
  pages,
  chunks,
  tables,
  assets,
  versions,
}: {
  doc: DocumentRow;
  tab: DetailTab;
  setTab: (t: DetailTab) => void;
  job: Job | null;
  pages: Page[];
  chunks: Chunk[];
  tables: TableArtifact[];
  assets: Asset[];
  versions: Version[];
}) {
  return (
    <>
      <DetailHead doc={doc} tab={tab} setTab={setTab} />
      {tab === "pipeline" && <Pipeline job={job} />}{" "}
      {tab === "pages" && (
        <PagesView pages={pages} tables={tables} chunks={chunks} markdown="" />
      )}{" "}
      {tab === "chunks" && <ChunkView chunks={chunks} />}{" "}
      {tab === "assets" && <AssetsView tables={tables} assets={assets} />}{" "}
      {tab === "versions" && <VersionsView versions={versions} />}
    </>
  );
}

export default function Home() {
  const [screen, setScreen] = useState<Screen>("documents"),
    [tab, setTab] = useState<DetailTab>("pipeline"),
    [docs, setDocs] = useState(demoDocs),
    [jobs, setJobs] = useState(demoJobs),
    [providers, setProviders] = useState<Provider[]>([]),
    [selected, setSelected] = useState(demoDocs[0]),
    [job, setJob] = useState<Job | null>(null),
    [pages, setPages] = useState<Page[]>([]),
    [chunks, setChunks] = useState(demoChunks),
    [tables, setTables] = useState(demoTables),
    [assets, setAssets] = useState(demoAssets),
    [versions, setVersions] = useState<Version[]>([]),
    [toast, setToast] = useState("");
  useEffect(() => {
    (async () => {
      const [rd, rj, rp] = await Promise.all([
        getJson<any[]>("/v1/documents?limit=50", []),
        getJson<Job[]>("/v1/jobs", demoJobs),
        getJson<Provider[]>("/v1/providers/health", []),
      ]);
      if (rd.length) {
        const m = rd.map(
          ({
            document: d,
            latest_version: v,
            latest_job_id,
          }: any): DocumentRow => ({
            id: d.id,
            versionId: v?.id,
            jobId: latest_job_id,
            title: d.title,
            file: d.filename,
            type: d.filename.split(".").pop().toUpperCase(),
            status: v?.status ?? "processing",
            version: v ? `v${v.revision}` : "—",
            pages: v?.page_count ?? 0,
            chunks: v?.chunk_count ?? 0,
            updated: new Date(d.updated_at).toLocaleString("tr-TR", {
              day: "2-digit",
              month: "short",
              year: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            }),
            versionCount: d.version_count ?? 1,
            tables: v?.table_count ?? 0,
            assets: v?.asset_count ?? 0,
          }),
        );
        setDocs([
          ...m,
          ...demoDocs.filter((d) => !m.some((x) => x.id === d.id)),
        ]);
      }
      setJobs([
        ...rj,
        ...demoJobs.filter((d) => !rj.some((x) => x.id === d.id)),
      ]);
      setProviders(rp);
    })();
  }, []);
  useEffect(() => {
    if (toast) {
      const id = setTimeout(() => setToast(""), 2800);
      return () => clearTimeout(id);
    }
  }, [toast]);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [screen, tab, selected.id]);
  async function open(d: DocumentRow) {
    setSelected(d);
    setTab("pipeline");
    setScreen("detail");
    if (!d.versionId) {
      setToast("Bu dokümanın yayımlanmış bir sürümü henüz yok.");
      return;
    }
    const [j, p, c, t, a, v] = await Promise.all([
      d.jobId ? getJson<Job | null>(`/v1/jobs/${d.jobId}`, null) : null,
      getJson<Page[]>(`/v1/versions/${d.versionId}/pages`, []),
      getJson<Chunk[]>(`/v1/versions/${d.versionId}/chunks`, demoChunks),
      getJson<TableArtifact[]>(
        `/v1/versions/${d.versionId}/tables`,
        demoTables,
      ),
      getJson<Asset[]>(`/v1/versions/${d.versionId}/assets`, demoAssets),
      getJson<Version[]>(`/v1/documents/${d.id}/versions`, []),
    ]);
    setJob(j);
    setPages(p);
    setChunks(c.length ? c : demoChunks);
    setTables(t.length ? t : demoTables);
    setAssets(a.length ? a : demoAssets);
    setVersions(v);
  }
  async function retry(j: Job) {
    const r = await fetch(`${API}/v1/versions/${j.document_version_id}/retry`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ from_stage: "extract" }),
    }).catch(() => null);
    setToast(
      r?.ok
        ? `${j.id} yeniden kuyruğa alındı`
        : `${j.id} için yeniden deneme hazır`,
    );
  }
  return (
    <div className="app">
      <Sidebar
        screen={screen}
        nav={setScreen}
        docs={docs.length}
        jobs={jobs.filter((j) => j.status === "running").length}
      />
      <main>
        {screen === "documents" ? (
          <Documents docs={docs} open={open} toast={setToast} />
        ) : screen === "jobs" ? (
          <Jobs jobs={jobs} docs={docs} retry={retry} />
        ) : screen === "providers" ? (
          <Providers items={providers} />
        ) : screen === "contract" ? (
          <Contract />
        ) : (
          <Detail
            doc={selected}
            tab={tab}
            setTab={setTab}
            job={job}
            pages={pages}
            chunks={chunks}
            tables={tables}
            assets={assets}
            versions={versions}
          />
        )}
      </main>
      {toast && (
        <div className="toast">
          <i />
          {toast}
        </div>
      )}
    </div>
  );
}
