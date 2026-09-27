"use client";

import { useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WORKSPACE = process.env.NEXT_PUBLIC_WORKSPACE_ID ?? "ws_local";
type Screen = "documents" | "jobs" | "providers" | "contract" | "detail";
type DetailTab = "pipeline" | "pages" | "chunks" | "assets" | "versions";
type UploadPhase =
  | "idle"
  | "registering"
  | "uploading"
  | "confirming"
  | "queued"
  | "running"
  | "done"
  | "partial"
  | "failed"
  | "error";
type UploadState = {
  phase: UploadPhase;
  fileName?: string;
  message?: string;
  jobId?: string;
};
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
  queued_at?: string;
  started_at?: string;
  finished_at?: string;
};
type Provider = {
  interface: string;
  implementation: string;
  healthy: boolean | null;
  location: string;
  note?: string;
};
type Page = {
  id: string;
  page_number: number;
  render_uri: string;
  parser: string;
  confidence: number | null;
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
type RegisterResponse = {
  document: {
    id: string;
    title: string;
    filename: string;
    version_count: number;
    updated_at: string;
  };
  version: Version;
  job_id: string;
  upload_url: string | null;
  deduplicated: boolean;
};
type DocumentListResponse = {
  document: RegisterResponse["document"];
  latest_version: Version | null;
  latest_job_id: string | null;
};

const stageMeta: Record<string, { name: string; via: string }> = {
  register: { name: "Kayıt", via: "API metadata kaydı" },
  render: { name: "Sayfa render", via: "PyMuPDF → PNG" },
  extract: { name: "Çıkarım", via: "Gemini veya Docling" },
  quality: { name: "Temel kontrol", via: "Sayfa hataları / response doğrulama" },
  vision: { name: "Vision enrichment", via: "Ayrı aşama uygulanmadı" },
  normalize: { name: "Normalization", via: "Henüz uygulanmadı" },
  chunk: { name: "Chunking", via: "Henüz uygulanmadı" },
  enrich: { name: "Chunk enrichment", via: "Henüz uygulanmadı" },
  embed: { name: "Embedding / index", via: "Henüz uygulanmadı" },
  publish: { name: "Çıktı kaydı", via: "Extraction JSON / Markdown" },
};
type Mode = "live" | "demo";

async function apiJson<T>(url: string, init?: RequestInit, expectedMode?: Mode): Promise<T> {
  const response = await fetch(url, init);
  if (expectedMode && response.headers.get("X-Docgrain-Mode") !== expectedMode) {
    throw new Error("API çalışma modu değişti veya doğrulanamadı. Listeyi yenileyin.");
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Keep the HTTP status when the response is not JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}
const documentRow = ({
  document: d,
  latest_version: v,
  latest_job_id,
}: DocumentListResponse): DocumentRow => ({
  id: d.id,
  versionId: v?.id,
  jobId: latest_job_id ?? undefined,
  title: d.title,
  file: d.filename,
  type: d.filename.split(".").pop()?.toUpperCase() ?? "FILE",
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
});
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
        M0 · PDF extraction prototipi
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
  upload,
  uploadState,
  mode,
}: {
  docs: DocumentRow[];
  open: (d: DocumentRow) => void;
  upload: (file: File) => Promise<void>;
  uploadState: UploadState;
  mode: Mode | null;
}) {
  const input = useRef<HTMLInputElement>(null);
  const busy = mode !== "live" || ["registering", "uploading", "confirming", "queued", "running"].includes(
    uploadState.phase,
  );
  return (
    <>
      <Head
        title="Dokümanlar"
        sub="Her yükleme yeni bir doküman ve ilk sürüm kaydı oluşturur. Deduplication ve mevcut dokümana yeni sürüm ekleme henüz yok."
        endpoint="GET /v1/documents"
      />
      <div className="wrap">
        <section className="drop">
          <div className="ico">
            <Icon name="upload" />
          </div>
          <div>
            <h3>PDF yükle</h3>
            <p>
              Şu anda yalnızca PDF işlenir. DOCX, TXT ve XLSX ilk ürün kapsamındadır,
              ancak henüz desteklenmez. Demo modu salt okunurdur.
            </p>
            {uploadState.phase !== "idle" && (
              <div className={`uploadState upload-${uploadState.phase}`} role="status">
                <span className="uploadDot" />
                <b>{uploadState.fileName}</b>
                <span>{uploadState.message}</span>
                {uploadState.jobId && <code>{uploadState.jobId}</code>}
              </div>
            )}
          </div>
          <input
            ref={input}
            type="file"
            hidden
            accept=".pdf,application/pdf"
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              void upload(file).finally(() => {
                if (input.current) input.current.value = "";
              });
            }}
          />
          <button
            className="btn pri dropAction"
            onClick={() => input.current?.click()}
            disabled={busy}
          >
            {mode === "demo" ? "Demo: yükleme kapalı" : mode === null ? "API bekleniyor" : busy ? "İşleniyor…" : "PDF seç"}
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
                {!docs.length && <tr><td colSpan={7}>Henüz doküman yok.</td></tr>}
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
}: {
  jobs: Job[];
  docs: DocumentRow[];
}) {
  const count = (s: string) => jobs.filter((j) => j.status === s).length;
  const current = (j: Job) => {
    const x = [...j.stages]
      .reverse()
      .find((s) => ["running", "failed", "done"].includes(s.status));
    return x ? stageMeta[x.stage]?.name : "Aşama bilgisi yok";
  };
  return (
    <>
      <Head
        title="İşler"
        sub="Kaydedilen job durumları gösterilir. Stage retry ve worker çökmesi sonrası otomatik recovery henüz uygulanmadı."
        endpoint="GET /v1/jobs"
      />
      <div className="wrap">
        <div className="stats">
          {[
            ["Kuyrukta", count("queued"), "kayıtlı queued işler", ""],
            ["Çalışan", count("running"), "kayıtlı running işler", "blue"],
            [
              "Kısmi",
              count("partial"),
              "sayfa düzeyi hata raporu var",
              "amber",
            ],
            ["Başarısız", count("failed"), "retry henüz yok", "red"],
            ["Toplam", jobs.length, "listelenen iş", ""],
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
              <Ep>GET /v1/jobs</Ep>
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
                          {j.stages.map((stage) => (
                             <i key={stage.stage} title={`${stage.stage}: ${stage.status}`}
                               className={stage.status === "done" ? "done" : stage.status === "running" ? "run" : stage.status === "failed" ? "err" : ""} />
                           ))}
                         </div>
                      </td>
                      <td>{current(j)}</td>
                      <td className="mono">{duration(j.duration_ms)}</td>
                      <td>
                        {["failed", "partial"].includes(j.status) && (
                          <span className="muted">Retry henüz yok</span>
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
        sub="Yapılandırma envanteri. Bu ekran provider bağlantılarını test etmez."
        endpoint="GET /v1/providers/health"
      />
      <div className="wrap">
        <div className="explain">
          <b>Mevcut durum:</b> Gemini ve Docling extraction yolları mevcut.
          Ek provider, embedding ve index adapter’ları henüz uygulanmadı.
          “Kontrol edilmedi” bağlantı veya model erişiminin doğrulanmadığını belirtir.
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
                <th>Açıklama</th>
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
                      {p.healthy === null ? "Kontrol edilmedi" : p.healthy ? "Doğrulandı" : "Etkin değil"}
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
function Contract() {
  return (
    <>
      <Head section="Referans" title="Mevcut API ve hedef yön" sub="M0 kapsamı; Canonical Knowledge Model henüz uygulanmadı." endpoint="GET /docs" />
      <div className="wrap">
        <section className="card pad">
          <h2>Canonical-first document-to-knowledge engine</h2>
          <p>Hedef: document → structural parse → Vision enrichment → reconciliation → canonical knowledge → projections.</p>
          <p>Canonical structured knowledge kaynak doğrusu olacak; Markdown, chunks, embeddings ve uygulama görünümleri ondan türetilecek.</p>
          <p>Bugün: PDF upload → page render → Gemini veya Docling → provider-specific document.json / document.md.</p>
          <p>PDF, DOCX, TXT ve XLSX ilk ürün kapsamıdır. Şu anda yalnızca PDF ingestion desteklenir.</p>
          <p>Core schema ile kullanıcı/domain schema ayrı kalacak. LUWI gelecekteki tüketicilerden biridir.</p>
          <p>Canonical model, normalization, manifest, chunking, indexing, structured patch ve crash recovery henüz yok.</p>
          <p>Jev, LangChain/LangGraph, çoklu provider, hybrid retrieval ve connectors ertelendi.</p>
          <a href={`${API}/docs`} target="_blank" rel="noreferrer">OpenAPI sözleşmesini aç</a>
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
  if (!job) return <EmptyState title="Job bilgisi yok" text="Bu kayıt için pipeline sonucu alınamadı." />;
  const stages = job.stages;
  const jobTime = job?.started_at ?? job?.queued_at;
  return (
    <div className="wrap">
      <section className="card">
        <header>
          <div>
            <h2>İş {job.id}</h2>
            <p className="note">
              {jobTime
                ? new Date(jobTime).toLocaleString("tr-TR")
                : "Zaman bilgisi yok"}{" "}
              · {duration(job.duration_ms)}
            </p>
          </div>
          <span className="sp">
            <Status status={job.status} />
          </span>
          <Ep>GET /v1/jobs/{job.id}</Ep>
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
              <p className="out">{s.summary ?? (s.status === "skipped" ? "Çalıştırılmadı." : "Aşama ayrıntısı kaydedilmedi.")}</p>
              {s.error && <p role="alert">{s.error}</p>}
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
        <b>Aşama kaydı:</b> Mevcut worker aşama özetlerini işlem sonunda kaydeder.
        Ayrıntılı canlı aşama ilerlemesi, stage retry ve crash recovery henüz yok.
        “Çıktı kaydı” extraction dosyalarını ifade eder; canonical manifest veya index üretmez.
        M0 öncesi kayıtlar geçmiş durum özetleridir ve uygulanmamış aşamalar için yanıltıcı değerler içerebilir.
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
  return <div className={`paperMock ${small ? "small" : ""}`}>Sayfa görseli mevcut değil.</div>;
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
    table = tables.find((t) => t.page_number === n);
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
          {pages.map((page) => (
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
              güven <b>{p?.confidence == null ? "ölçülmedi" : p.confidence.toFixed(2)}</b>
            </code>
            <code className="chip">{p?.parser ?? "bilinmiyor"}</code>
            <label className="switch">
              <input type="checkbox" disabled /> kaynak kutuları (henüz yok)
            </label>
          </div>
          <PageSheet page={n} src={p?.render_uri} />
          <code className="mono muted">{p?.render_uri}</code>
        </div>
        <div className="extract">
          <div className="minitabs">
            <button className="minitab" aria-selected>
              Doküman Markdown
            </button>
            <button className="minitab" disabled>JSON (API üzerinden)</button>
            <button className="minitab" disabled>Tablolar</button>
            <button className="minitab" disabled>Görseller</button>
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
              <p>Bu sürüm için extraction Markdown mevcut değil. Demo modunda dosya üretilmez.</p>
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
        <b>Extraction önizlemesi:</b> Solda seçilen sayfa, sağda dokümanın tamamının
        Markdown çıktısı bulunur. Bu çıktı henüz canonical knowledge değildir.
        Sayfa hataları job kaydında tutulur; confidence ölçülmez.
      </div>
    </div>
  );
}
function ChunkView({ chunks }: { chunks: Chunk[] }) {
  const [selected, setSelected] = useState(
      chunks.find((c) => c.id === "chk_06") ?? chunks[0],
    ),
    [neighbors, setNeighbors] = useState<Neighbor[]>([]),
    [neighborError, setNeighborError] = useState("");
  useEffect(() => {
    let active = true;
    setNeighbors([]); setNeighborError("");
    if (selected) apiJson<Neighbor[]>(`${API}/v1/chunks/${selected.id}/neighbors?limit=5`, undefined, "demo")
      .then((items) => { if (active) setNeighbors(items); })
      .catch((error) => { if (active) setNeighborError(String(error)); });
    return () => { active = false; };
  }, [selected]);
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
                <span>Kaynak sayfa numaraları</span>
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
              <label className="fieldLabel">Demo komşuları — simülasyon, gerçek embedding değil</label>
              {neighborError && <p role="alert">{neighborError}</p>}
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
      <div className="explain">
        Chunk üretimi ve embedding benzerliği henüz uygulanmadı.
        Demo modunda gösterilen chunk ve komşular sentetik örneklerdir.
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
        text="Live pipeline bağımsız tablo/görsel catalog üretmiyor. Extraction JSON içindeki parser verileri ayrı catalog değildir."
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
  if (!versions.length) return <EmptyState title="Sürüm bilgisi yok" text="Bu doküman için sürüm kaydı alınamadı." />;
  const sorted = [...versions].sort((a, b) => a.revision - b.revision);
  return <div className="wrap">
    {sorted.map((v, i) => <VersionBox key={v.id} v={v} current={i === sorted.length - 1} />)}
    <div className="explain">Bunlar kayıtlı sürüm sayaçlarıdır. Live diff endpoint’i yalnızca sayaç farkı verir.
      İçerik diff’i, Structured Knowledge Patch ve aynı dokümana yeni sürüm yükleme henüz uygulanmadı.</div>
  </div>;
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
  markdown,
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
  markdown: string;
}) {
  return (
    <>
      <DetailHead doc={doc} tab={tab} setTab={setTab} />
      {tab === "pipeline" && <Pipeline job={job} />}{" "}
      {tab === "pages" && (
        <PagesView pages={pages} tables={tables} chunks={chunks} markdown={markdown} />
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
    [mode, setMode] = useState<Mode | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [detailLoading, setDetailLoading] = useState(false),
    [detailError, setDetailError] = useState(""),
    [docs, setDocs] = useState<DocumentRow[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [providers, setProviders] = useState<Provider[]>([]),
    [selected, setSelected] = useState<DocumentRow | null>(null),
    [job, setJob] = useState<Job | null>(null),
    [pages, setPages] = useState<Page[]>([]),
    [chunks, setChunks] = useState<Chunk[]>([]),
    [tables, setTables] = useState<TableArtifact[]>([]),
    [assets, setAssets] = useState<Asset[]>([]),
    [versions, setVersions] = useState<Version[]>([]),
    [markdown, setMarkdown] = useState(""),
    [uploadState, setUploadState] = useState<UploadState>({ phase: "idle" }),
    [toast, setToast] = useState("");
  const requestId = useRef(0);

  async function refresh() {
    const request = ++requestId.current;
    setLoading(true); setError(""); setMode(null);
    setDocs([]); setJobs([]); setProviders([]);
    setSelected(null); setScreen("documents");
    try {
      const health = await apiJson<{ mode: Mode }>(`${API}/healthz`);
      if (health.mode !== "live" && health.mode !== "demo") throw new Error("API çalışma modu doğrulanamadı.");
      const [documents, nextJobs, nextProviders] = await Promise.all([
        apiJson<DocumentListResponse[]>(`${API}/v1/documents?limit=50`, undefined, health.mode),
        apiJson<Job[]>(`${API}/v1/jobs`, undefined, health.mode),
        apiJson<Provider[]>(`${API}/v1/providers/health`, undefined, health.mode),
      ]);
      if (request !== requestId.current) return;
      setMode(health.mode);
      setDocs(documents.map(documentRow)); setJobs(nextJobs); setProviders(nextProviders);
    } catch (cause) {
      if (request === requestId.current) setError(`API verileri alınamadı: ${String(cause)}`);
    } finally {
      if (request === requestId.current) setLoading(false);
    }
  }
  useEffect(() => { void refresh(); return () => { requestId.current += 1; }; }, []);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 4000);
    return () => clearTimeout(id);
  }, [toast]);
  useEffect(() => { window.scrollTo({ top: 0, behavior: "auto" }); }, [screen, tab, selected?.id]);

  async function open(d: DocumentRow) {
    const request = ++requestId.current;
    setSelected(d); setTab("pipeline"); setScreen("detail");
    setJob(null); setPages([]); setChunks([]); setTables([]); setAssets([]); setVersions([]); setMarkdown("");
    setDetailError(""); setDetailLoading(true);
    try {
      if (!mode) throw new Error("API modu doğrulanamadı.");
      if (!d.versionId) throw new Error("Bu dokümanın sürüm kaydı yok.");
      const [j, p, c, t, a, v] = await Promise.all([
        d.jobId ? apiJson<Job>(`${API}/v1/jobs/${d.jobId}`, undefined, mode) : null,
        apiJson<Page[]>(`${API}/v1/versions/${d.versionId}/pages`, undefined, mode),
        apiJson<Chunk[]>(`${API}/v1/versions/${d.versionId}/chunks`, undefined, mode),
        apiJson<TableArtifact[]>(`${API}/v1/versions/${d.versionId}/tables`, undefined, mode),
        apiJson<Asset[]>(`${API}/v1/versions/${d.versionId}/assets`, undefined, mode),
        apiJson<Version[]>(`${API}/v1/documents/${d.id}/versions`, undefined, mode),
      ]);
      let md = "";
      if (mode === "live") {
        const response = await fetch(`${API}/v1/documents/${d.id}/versions/${d.versionId}/artifacts/document.md`);
        if (response.headers.get("X-Docgrain-Mode") !== "live") throw new Error("API modu değişti; listeyi yenileyin.");
        if (response.ok) md = await response.text();
        else if (response.status !== 404) throw new Error(`Markdown okunamadı: HTTP ${response.status}`);
      }
      if (request !== requestId.current) return;
      setJob(j); setPages(mode === "demo" ? p.map((page) => ({ ...page, render_uri: "" })) : p); setChunks(c); setTables(t); setAssets(a); setVersions(v); setMarkdown(md);
    } catch (cause) {
      if (request === requestId.current) setDetailError(String(cause));
    } finally {
      if (request === requestId.current) setDetailLoading(false);
    }
  }
  async function upload(file: File) {
    if (mode !== "live") return;
    const terminal = new Set(["done", "partial", "failed"]);
    try {
      setUploadState({
        phase: "registering",
        fileName: file.name,
        message: "Doküman ve ilk sürüm kaydı açılıyor…",
      });
      const registration = await apiJson<RegisterResponse>(`${API}/v1/documents`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          workspace_id: WORKSPACE,
          filename: file.name,
          mime_type: file.type || "application/octet-stream",
          byte_size: file.size,
        }),
      }, "live");

      const pendingRow = documentRow({
        document: registration.document,
        latest_version: registration.version,
        latest_job_id: registration.job_id,
      });
      setDocs((current) => [pendingRow, ...current.filter((d) => d.id !== pendingRow.id)]);

      if (!registration.deduplicated) {
        if (!registration.upload_url) throw new Error("API bir upload URL döndürmedi");
        setUploadState({
          phase: "uploading",
          fileName: file.name,
          jobId: registration.job_id,
          message: "Orijinal dosya MinIO’ya yazılıyor…",
        });
        const form = new FormData();
        form.append("file", file, file.name);
        await apiJson<{ status: string }>(registration.upload_url, {
          method: "PUT",
          body: form,
        }, "live");

        setUploadState({
          phase: "confirming",
          fileName: file.name,
          jobId: registration.job_id,
          message: "Upload kontrol edilip job kuyruğa alınıyor…",
        });
        await apiJson<{ status: string; job_id: string }>(
          `${API}/v1/documents/${registration.document.id}/versions/${registration.version.id}/uploaded`,
          { method: "POST" }, "live",
        );
      }

      setUploadState({
        phase: "queued",
        fileName: file.name,
        jobId: registration.job_id,
        message: registration.deduplicated
          ? "Aynı içerik daha önce kaydedilmiş. Mevcut sürüm kullanılıyor."
          : "Job kuyrukta; worker bekleniyor…",
      });

      for (let poll = 0; poll < 450; poll += 1) {
        const currentJob = await apiJson<Job>(`${API}/v1/jobs/${registration.job_id}`, undefined, "live");
        setJobs((current) => [
          currentJob,
          ...current.filter((item) => item.id !== currentJob.id),
        ]);
        setDocs((current) =>
          current.map((item) =>
            item.id === registration.document.id
              ? { ...item, status: currentJob.status }
              : item,
          ),
        );
        setUploadState({
          phase: currentJob.status as UploadPhase,
          fileName: file.name,
          jobId: currentJob.id,
          message: terminal.has(currentJob.status)
            ? statusLabel(currentJob.status)
            : currentJob.status === "running"
              ? "Worker pipeline’ı çalıştırıyor…"
              : "Job kuyrukta; worker bekleniyor…",
        });
        if (terminal.has(currentJob.status)) {
          const refreshed = await apiJson<DocumentListResponse>(
            `${API}/v1/documents/${registration.document.id}`, undefined, "live",
          );
          const finalRow = documentRow(refreshed);
          setDocs((current) => [
            finalRow,
            ...current.filter((item) => item.id !== finalRow.id),
          ]);
          setToast(`${file.name}: ${statusLabel(currentJob.status)}`);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }

      setUploadState({
        phase: "error",
        fileName: file.name,
        jobId: registration.job_id,
        message: "Otomatik izleme süresi doldu; güncel job durumunu listeyi yenileyerek kontrol edin.",
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Bilinmeyen upload hatası";
      setUploadState({ phase: "error", fileName: file.name, message });
      setToast(`${file.name} yüklenemedi: ${message}`);
    }
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
        <div className="modeNotice" role="status">
          {mode === "demo" ? "DEMO — salt okunur sentetik veriler. Stage, chunk, tablo, görsel ve diff örnekleri gerçek işlem sonucu değildir."
            : mode === "live" ? "LIVE — gerçek kayıtlar. PDF extraction mevcut; canonical model, chunking, index ve recovery henüz yok." : "API çalışma modu bekleniyor."}
          <button className="btn sm" onClick={() => void refresh()} disabled={loading || ["registering", "uploading", "confirming", "queued", "running"].includes(uploadState.phase)}>Listeyi yenile</button>
        </div>
        {loading ? <EmptyState title="Yükleniyor" text="API çalışma modu ve kayıtlar alınıyor." />
          : error ? <div role="alert"><EmptyState title="API hatası" text={error} /></div>
          : screen === "documents" ? (
          <Documents
            docs={docs}
            open={open}
            upload={upload}
            uploadState={uploadState}
            mode={mode}
          />
        ) : screen === "jobs" ? (
          <Jobs jobs={jobs} docs={docs} />
        ) : screen === "providers" ? (
          <Providers items={providers} />
        ) : screen === "contract" ? (
          <Contract />
        ) : detailLoading ? <EmptyState title="Yükleniyor" text="Doküman kayıtları alınıyor." />
          : detailError ? <div role="alert"><EmptyState title="Doküman okunamadı" text={detailError} /></div>
          : selected ? (
          <Detail
            key={selected.id}
            doc={selected}
            tab={tab}
            setTab={setTab}
            job={job}
            pages={pages}
            chunks={chunks}
            tables={tables}
            assets={assets}
            versions={versions}
            markdown={markdown}
          />
        ) : null}
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
