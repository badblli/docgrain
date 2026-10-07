"use client";

import { Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";


import { useEffect, useRef, useState } from "react";
import { Icon, Head, Ep, EmptyState, pageBody, pageGutter } from "./components/console-ui";
import { Sidebar } from "./components/sidebar";
import { WorkspaceSettings } from "./components/settings/workspace-settings";
import { TryView } from "./components/try/try-view";
import { useRecordJob, jobActive } from "./components/record-job-progress";
import { createUploadQueue, sha256 } from "../lib/u1-upload";
import { Documents } from "./components/documents";
import { InformationView } from "./components/information/information";
import { SummaryView } from "./components/summary";
import { QuestionsView } from "./components/questions";
import { useWorkspaceReview } from "./components/workspace-review";
import { formatWorkspaceName, type WorkspaceItem, type Screen, type DocumentRow, type UploadState, type Mode } from "./components/console-types";
import { DeveloperModeContext, useDeveloperMode } from "./components/developer-mode";
import { AIOutputView } from "./components/canonical/ai-output";
import { ReviewWorkspace } from "./components/canonical/review-workspace";
import { Assets as CanonicalAssets, Issues as CanonicalIssues, Overview as CanonicalOverview,
  ProvenanceView, Raw as CanonicalRaw, Structure as CanonicalStructure, Tables as CanonicalTables,
  type Knowledge } from "./components/canonical/inspector";


const screenContent = pageBody;
const technicalCard = "bg-paper border border-solid border-line rounded-card shadow-none overflow-hidden [&_>_header]:border-b [&_>_header]:border-solid [&_>_header]:border-b-line2 [&_>_header]:flex [&_>_header]:items-center [&_>_header]:flex-wrap [&_>_header_h2]:text-sm [&_>_header_h2]:font-semibold [&_>_header_h2]:tracking-[-0.01em] [&_>_header]:py-3 [&_>_header]:px-4 [&_>_header]:gap-2 [&_>_header_h2]:m-0";
const technicalNote = "bg-sheet border border-solid border-line2 border-l-[2.5px] border-l-faint rounded-[0_var(--radius)_var(--radius)_0] text-xs text-ink2 leading-[1.55] [&_b]:text-ink p-3";
const technicalChip = "font-normal text-2xs font-mono rounded-sm bg-sheet border border-solid border-line text-ink2 [button&]:[&:hover]:border-accent [&_b]:font-semibold [&_b]:text-ink py-1 px-2";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const DEFAULT_WORKSPACE = process.env.NEXT_PUBLIC_WORKSPACE_ID ?? "ws_local";

type DetailTab = "history" | "review" | "ai-output" | "overview" | "structure" | "tables" | "assets" | "issues" | "provenance" | "pages" | "pipeline" | "versions" | "raw";
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

async function readDocuments(workspaceId: string, mode: Mode, signal?: AbortSignal): Promise<DocumentListResponse[]> {
  const rows: DocumentListResponse[] = [];
  let page: DocumentListResponse[];
  do {
    page = await apiJson<DocumentListResponse[]>(`${API}/v1/documents?limit=50&offset=${rows.length}&workspace_id=${encodeURIComponent(workspaceId)}`, { signal, cache: "no-store" }, mode);
    rows.push(...page);
  } while (page.length === 50);
  return rows;
}

const stageMeta: Record<string, { name: string; via: string }> = {
  register: { name: "Kayıt", via: "API metadata kaydı" },
  render: { name: "Sayfa render", via: "PyMuPDF → PNG" },
  extract: { name: "Çıkarım", via: "Gemini veya Docling" },
  quality: { name: "Temel kontrol", via: "Sayfa hataları / response doğrulama" },
  vision: { name: "Vision enrichment", via: "Ayrı aşama uygulanmadı" },
  normalize: { name: "Normalization", via: "Canonical AI çıktısı" },
  chunk: { name: "Chunking", via: "Canonical structure-aware chunks" },
  enrich: { name: "Chunk enrichment", via: "Henüz uygulanmadı" },
  embed: { name: "Embedding / index", via: "Henüz uygulanmadı" },
  publish: { name: "Revision / artifact kaydı", via: "Canonical revision ve doğrulanmış çıktı paketi" },
};


class HttpError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

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
    throw new HttpError(response.status, detail);
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
  updated: new Date(d.updated_at).toLocaleString("tr-TR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }),
  versionCount: d.version_count ?? 1,
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
const documentStatusLabel = (status: string) => status === "done" ? "Hazır"
  : ["running", "processing"].includes(status) ? "Hazırlanıyor"
  : ["queued", "pending"].includes(status) ? "Sırada" : "Kontrol edilmeli";
const pillClass = (s: string) =>
  s === "done"
    ? "bg-ok-soft text-ok"
    : s === "running" || s === "processing"
      ? "bg-accent-soft text-accent"
      : s === "partial"
        ? "bg-warn-soft text-warn"
        : s === "failed"
          ? "bg-danger-soft text-danger"
          : "bg-idle-soft text-idle";
function Status({ status }: { status: string }) {
  const developerMode = useDeveloperMode();
  return (
    <Badge variant="outline" className={pillClass(status)}>
      <i className="w-[6px] h-[6px] rounded-pill bg-current" />
      {developerMode ? statusLabel(status) : documentStatusLabel(status)}
    </Badge>
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
      <div className={screenContent}>
        <div className="grid grid-cols-[repeat(5,_1fr)] bg-line2 rounded-card overflow-hidden border border-solid border-line max-[1180px]:grid-cols-[repeat(3,_1fr)] max-[780px]:grid-cols-[1fr_1fr] max-[560px]:grid-cols-[1fr] gap-1">
          {[
            ["Kuyrukta", count("queued"), "kayıtlı queued işler", ""],
            ["Çalışan", count("running"), "kayıtlı running işler", "text-accent"],
            [
              "Kısmi",
              count("partial"),
              "sayfa düzeyi hata raporu var",
              "text-warn",
            ],
            ["Başarısız", count("failed"), "retry henüz yok", "text-danger"],
            ["Toplam", jobs.length, "listelenen iş", ""],
          ].map((x) => (
            <div className="bg-paper py-3 px-4" key={String(x[0])}>
              <div className="text-2xs tracking-[0.07em] uppercase text-faint font-semibold">{x[0]}</div>
              <div className={cn(`text-lg font-semibold tracking-[-0.02em] mt-1 ${x[3]}`)}>{x[1]}</div>
              <div className="text-2xs text-muted mt-1">{x[2]}</div>
            </div>
          ))}
        </div>
        <section className={technicalCard}>
          <header>
            <h2>İş kuyruğu</h2>
            <p className="text-2xs text-muted m-0">
              Şerit, 10 aşamanın hangisine kadar gelindiğini gösterir.
            </p>
            <span className="ml-auto">
              <Ep>GET /v1/jobs</Ep>
            </span>
          </header>
          <div className="overflow-x-auto">
            <Table containerClassName="overflow-visible" className="[&_td]:whitespace-normal [table&]:w-full [table&]:border-collapse [table&]:text-xs [table&]:[&_th]:text-left [table&]:[&_th]:text-2xs [table&]:[&_th]:tracking-[0.07em] [table&]:[&_th]:uppercase [table&]:[&_th]:text-faint [table&]:[&_th]:font-semibold [table&]:[&_th]:border-b [table&]:[&_th]:border-solid [table&]:[&_th]:border-b-line [table&]:[&_th]:whitespace-nowrap [table&]:[&_td]:border-b [table&]:[&_td]:border-solid [table&]:[&_td]:border-b-line2 [table&]:[&_td]:align-[middle] [table&]:[&_tbody_tr:last-child_td]:border-b-0 [&_th:nth-child(2)]:w-[24%] [table&]:[&_th]:py-2 [table&]:[&_th]:px-3 [table&]:[&_td]:p-3">
              <TableHeader>
                <TableRow>
                  <TableHead>İş</TableHead>
                  <TableHead>Belge</TableHead>
                  <TableHead>Durum</TableHead>
                  <TableHead>Aşamalar</TableHead>
                  <TableHead>Şu an</TableHead>
                  <TableHead>Süre</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.map((j) => {
                  return (
                    <TableRow key={j.id}>
                      <TableCell className="font-mono text-2xs">{j.id}</TableCell>
                      <TableCell>
                        {docs.find((d) => d.id === j.document_id)?.title ??
                          j.document_id}
                      </TableCell>
                      <TableCell>
                        <Status status={j.status} />
                      </TableCell>
                      <TableCell>
                        <div className="flex w-[150px] gap-1">
                          {j.stages.map((stage) => (
                             <i key={stage.stage} title={`${stage.stage}: ${stage.status}`}
                               className={cn("block h-[5px] flex-1 rounded-xs", stage.status === "done" ? "bg-ok" : stage.status === "running" ? "bg-accent" : stage.status === "failed" ? "bg-danger" : "bg-idle-soft")} />
                           ))}
                         </div>
                      </TableCell>
                      <TableCell>{current(j)}</TableCell>
                      <TableCell className="font-mono text-2xs">{duration(j.duration_ms)}</TableCell>
                      <TableCell>
                        {["failed", "partial"].includes(j.status) && (
                          <span className="text-muted">Retry henüz yok</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
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
      <div className={screenContent}>
        <div className={technicalNote}>
          <b>Mevcut durum:</b> Gemini ve Docling extraction yolları mevcut.
          Ek provider, embedding ve index adapter’ları henüz uygulanmadı.
          “Kontrol edilmedi” bağlantı veya model erişiminin doğrulanmadığını belirtir.
        </div>
        <section className={technicalCard}>
          <header>
            <h2>Bağlı sağlayıcılar</h2>
            <span className="ml-auto">
              <Ep>GET /v1/providers/health</Ep>
            </span>
          </header>
          <Table containerClassName="overflow-visible" className="[&_td]:whitespace-normal [table&]:w-full [table&]:border-collapse [table&]:text-xs [table&]:[&_th]:text-left [table&]:[&_th]:text-2xs [table&]:[&_th]:tracking-[0.07em] [table&]:[&_th]:uppercase [table&]:[&_th]:text-faint [table&]:[&_th]:font-semibold [table&]:[&_th]:border-b [table&]:[&_th]:border-solid [table&]:[&_th]:border-b-line [table&]:[&_th]:whitespace-nowrap [table&]:[&_td]:border-b [table&]:[&_td]:border-solid [table&]:[&_td]:border-b-line2 [table&]:[&_td]:align-[middle] [table&]:[&_tbody_tr:last-child_td]:border-b-0 [table&]:[&_th]:py-2 [table&]:[&_th]:px-3 [table&]:[&_td]:p-3">
            <TableHeader>
              <TableRow>
                <TableHead>Arayüz</TableHead>
                <TableHead>Uygulama</TableHead>
                <TableHead>Durum</TableHead>
                <TableHead>Açıklama</TableHead>
                <TableHead>Konum</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((p, i) => (
                <TableRow key={i}>
                  <TableCell className="font-mono text-2xs font-semibold">
                    {p.interface}
                    {p.interface === "VisionProvider" && i > 2 ? " (alt)" : ""}
                  </TableCell>
                  <TableCell>{p.implementation}</TableCell>
                  <TableCell>
                    <span className={cn(`inline-flex items-center text-2xs font-semibold rounded-pill whitespace-nowrap gap-1 py-1 px-2 ${p.healthy ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn"}`)}>
                      <i className="w-[6px] h-[6px] rounded-pill bg-current" />
                      {p.healthy === null ? "Kontrol edilmedi" : p.healthy ? "Doğrulandı" : "Etkin değil"}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted">{p.note}</TableCell>
                  <TableCell>
                    <code className={technicalChip}>{p.location}</code>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      </div>
    </>
  );
}
function Contract() {
  return (
    <>
      <Head section="Referans" title="Mevcut API ve hedef yön" sub="M1 canonical revision kayıtları ve read-only inspection." endpoint="GET /docs" />
      <div className={screenContent}>
        <section className="bg-paper border border-solid border-line rounded-card shadow-none overflow-hidden [&_>_header]:border-b [&_>_header]:border-solid [&_>_header]:border-b-line2 [&_>_header]:flex [&_>_header]:items-center [&_>_header]:flex-wrap [&_>_header_h2]:text-sm [&_>_header_h2]:font-semibold [&_>_header_h2]:tracking-[-0.01em] [&_>_header]:py-3 [&_>_header]:px-4 [&_>_header]:gap-2 [&_>_header_h2]:m-0 p-4">
          <h2>Canonical-first document-to-knowledge engine</h2>
          <p>Hedef: document → structural parse → Vision enrichment → reconciliation → canonical knowledge → projections.</p>
          <p>Canonical structured knowledge kaynak doğrusu olacak; Markdown, chunks, embeddings ve uygulama görünümleri ondan türetilecek.</p>
          <p>PDF, DOCX, TXT, XLSX, PNG ve JPEG → canonical JSON. Taranmış PDF ve görsellerde yerel Türkçe/İngilizce OCR kullanılır; sonuç kaynak incelemesi gerektirir. PDF sayfa render’ları ve özgün görsel dosyaları korunur.</p>
          <p>Core schema ile kullanıcı/domain schema ayrı kalacak; sektöre özel mantık çekirdeğin dışında kalır.</p>
          <p>Canonical revision, ortak AI JSON/Markdown, chunks ve checksum manifest yayını mevcut. Vision reconciliation, otomatik semantic extraction/indexing, structured patch ve crash recovery henüz yok.</p>
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
  knowledge,
}: {
  doc: DocumentRow;
  tab: DetailTab;
  setTab: (t: DetailTab) => void;
  knowledge: Knowledge | null;
}) {
  const developerMode = useDeveloperMode();
  const primaryTabs: [DetailTab, string, string][] = [
    ["review", "Oku", ""], ["history", "Geçmiş", ""],
  ];
  const technicalTabs: [DetailTab, string, string][] = [
    ["ai-output", "AI çıktısı", ""],
    ["overview", "Özet", ""],
    ["structure", "Yapı", String(knowledge?.snapshot.structure.length ?? "—")],
    ["tables", "Tablolar", String(knowledge?.snapshot.structure.filter((n) => n.kind === "table").length ?? "—")],
    ["assets", "Görseller", String(knowledge ? Math.max(
      knowledge.snapshot.structure.filter((n) => n.kind === "asset" || n.kind === "chart").length,
      knowledge.snapshot.metadata.structural_parse?.coverage?.item_counts?.picture ?? 0,
    ) : "—")],
    ["issues", "Eksikler", String(knowledge?.snapshot.metadata.structural_parse?.issues?.length ?? "—")],
    ["provenance", "Kaynak kanıtları", String(knowledge?.snapshot.evidence.length ?? "—")],
    ["pages", "Sayfalar", String(doc.pages)],
    ["pipeline", "İşlem kaydı", ""],
    ["versions", "Kaynak sürümleri", String(doc.versionCount)],
    ["raw", "Ham veri", ""],
  ];
  const renderTab = (t: [DetailTab, string, string]) => (
    <TabsTrigger value={t[0]} key={t[0]} className="h-auto rounded-none border-0 border-b-2 border-transparent bg-transparent px-3 py-2 text-sm text-muted shadow-none data-[state=active]:border-accent data-[state=active]:bg-transparent data-[state=active]:text-accent data-[state=active]:shadow-none">
      {t[1]}{t[2] && <span className="ml-1 font-mono text-2xs text-faint">{t[2]}</span>}
    </TabsTrigger>
  );
  return (
    <header className="bg-transparent border-b-0 border-solid border-b-line pt-10 pb-0 static top-0 z-[20] max-[560px]:[&_h1]:wrap-anywhere w-full min-w-0 [&_h1]:text-2xl [&_h1]:tracking-[var(--tracking-display)] [&_h1]:font-semibold max-[560px]:pt-6 max-[560px]:pb-0 px-4 md:px-6 xl:px-10">
      <div className="hidden items-center text-2xs text-muted mb-2 [&_b]:text-line [&_b]:font-normal max-[560px]:wrap-anywhere gap-2">
        <span>Çalışma alanı</span>
        <b>›</b>
        <span>Belgeler</span>
        <b>›</b>
        <span>{doc.title}</span>
      </div>
      <div className="flex items-start flex-wrap gap-3">
        <div>
          <h1>{doc.title}</h1>
          <p className="text-muted mt-1 mb-0 max-w-[74ch] max-[560px]:wrap-anywhere font-mono text-2xs mx-0">
            {doc.file} · {doc.type === "PDF" ? `${doc.pages} sayfa` :
              ["PNG", "JPG", "JPEG"].includes(doc.type) ? "Kaynak görseli" : doc.type} · sürüm {doc.version}
          </p>
        </div>
        <div className="ml-auto flex items-center max-[560px]:mt-2 max-[560px]:mb-0 max-[560px]:w-full max-[560px]:justify-start gap-2 max-[560px]:mx-0">
          <Status status={doc.status} />
          {tab !== "review" && <Ep>GET /v1/documents/{doc.id}/knowledge</Ep>}
        </div>
      </div>
      <div className="mt-3 min-w-0 overflow-x-auto"><TabsList aria-label="Belge bölümleri" className="h-auto w-max justify-start gap-1 rounded-none bg-transparent p-0">
        {primaryTabs.map(renderTab)}
        {developerMode && technicalTabs.map(renderTab)}
      </TabsList></div>
    </header>
  );
}
function Pipeline({ job }: { job: Job | null }) {
  if (!job) return <EmptyState title="Job bilgisi yok" text="Bu kayıt için pipeline sonucu alınamadı." />;
  const stages = job.stages;
  const jobTime = job?.started_at ?? job?.queued_at;
  return (
    <div className={screenContent}>
      <section className={technicalCard}>
        <header>
          <div>
            <h2>İş {job.id}</h2>
            <p className="text-2xs text-muted m-0">
              {jobTime
                ? new Date(jobTime).toLocaleString("tr-TR")
                : "Zaman bilgisi yok"}{" "}
              · {duration(job.duration_ms)}
            </p>
          </div>
          <span className="ml-auto">
            <Status status={job.status} />
          </span>
          <Ep>GET /v1/jobs/{job.id}</Ep>
        </header>
        <div className="flex gap-1 p-4">
          {stages.map((s) => (
            <div
              key={s.stage}
              className="min-w-0 flex-1"
            >
              <div className={cn("h-1.5 rounded-xs", s.status === "done" ? "bg-ok" : s.status === "running" ? "bg-accent" : s.status === "failed" ? "bg-danger" : "bg-idle-soft")} />
              <div className="text-2xs text-ink2 mt-1 whitespace-nowrap overflow-hidden text-ellipsis font-medium">{stageMeta[s.stage]?.name}</div>
            </div>
          ))}
        </div>
        {stages.map((s, i) => (
          <div
            className={cn("grid grid-cols-[26px_minmax(0,1fr)] gap-x-3 px-4", s.status === "done" ? "text-ok" : s.status === "running" ? "text-accent" : s.status === "failed" ? "text-danger" : "text-idle")}
            key={s.stage}
          >
            <div className="flex flex-col items-center">
              <i className="w-[11px] h-[11px] rounded-pill border-[2px] border-solid border-paper [box-shadow:0_0_0_1.5px_currentColor] mt-4 flex-none" />
              <i className="flex-1 w-[1.5px] bg-line mt-1 mb-0 [div:last-child_&]:hidden mx-0" />
            </div>
            <div className="border-b border-solid border-b-line2 min-w-0 [div:last-child_&]:border-b-0 py-3 px-0">
              <div className="flex items-center flex-wrap gap-2">
                <span className="font-semibold">
                  {i + 1}. {stageMeta[s.stage]?.name}
                </span>
                <Badge variant="outline" className={pillClass(s.status)}>
                  {statusLabel(s.status)}
                </Badge>
                <code className={technicalChip}>
                  {s.provider ?? stageMeta[s.stage]?.via}
                </code>
                <span className="ml-auto font-normal text-2xs font-mono text-faint">
                  {s.duration_ms ? duration(s.duration_ms) : "—"}
                </span>
              </div>
              <p className="text-muted text-xs mt-1 mb-0 mx-0">{s.summary ?? (s.status === "skipped" ? "Çalıştırılmadı." : "Aşama ayrıntısı kaydedilmedi.")}</p>
              {s.error && <p role="alert">{s.error}</p>}
              {s.attributes && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {Object.entries(s.attributes)
                    .slice(0, 5)
                    .map(([k, v]) => (
                      <code className={technicalChip} key={k}>
                        {k} <b>{String(v)}</b>
                      </code>
                    ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </section>
      <div className={technicalNote}>
        <b>Aşama kaydı:</b> Mevcut worker aşama özetlerini işlem sonunda kaydeder.
        Ayrıntılı canlı aşama ilerlemesi, stage retry ve crash recovery henüz yok.
        Yeni işler canonical revision, ortak AI çıktısı, chunks ve checksum manifesti yayımlar.
        Bu görünüm işin çalıştırıldığı tarihteki aşamaları gösterir; sonradan üretilen çıktı geçmiş job kaydını değiştirmez.
        Güncel yayımlanmış paketi AI çıktısı sekmesinden inceleyebilirsiniz. Embedding ve index otomatik üretilmez.
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
    return <div className={cn("relative overflow-hidden rounded-xs border border-line bg-paper", small && "min-h-[105px]")}>
      <img className="block h-auto w-full" src={src} alt={`Sayfa ${page} önizlemesi`} />
    </div>;
  }
  return <div className={cn("grid aspect-[1654/2339] w-full place-items-center rounded-xs border border-line bg-paper p-3 text-center text-xs text-muted", small && "min-h-[105px]")}>Sayfa görseli mevcut değil.</div>;
}

function PagesView({
  pages,
  markdown,
}: {
  pages: Page[];
  markdown: string;
}) {
  const [n, setN] = useState(pages[0]?.page_number ?? 1),
    p = pages.find((x) => x.page_number === n);
  if (!pages.length) {
    return (
      <EmptyState
        title="Sayfa render’ları henüz hazır değil"
        text="Pipeline tamamlandığında gerçek sayfa PNG’leri burada görünecek."
      />
    );
  }
  return (
    <div className={screenContent}>
      <section className="bg-paper border border-solid border-line rounded-card shadow-none overflow-hidden [&_>_header]:border-b [&_>_header]:border-solid [&_>_header]:border-b-line2 [&_>_header]:flex [&_>_header]:items-center [&_>_header]:flex-wrap [&_>_header_h2]:text-sm [&_>_header_h2]:font-semibold [&_>_header_h2]:tracking-[-0.01em] grid grid-cols-[104px_minmax(280px,_1fr)_minmax(320px,_1.1fr)] min-h-160 max-[1180px]:grid-cols-[88px_minmax(0,_1fr)] max-[560px]:grid-cols-[64px_minmax(0,_1fr)] [&_>_header]:py-3 [&_>_header]:px-4 [&_>_header]:gap-2 [&_>_header_h2]:m-0">
        <div className="border-r border-solid border-r-line flex flex-col max-h-[78vh] overflow-auto bg-sheet py-3 px-2 gap-2 max-[560px]:py-2 max-[560px]:px-1">
          {pages.map((page) => (
            <Button variant="ghost"
              className="h-auto whitespace-normal bg-transparent border-0 relative rounded-xs p-0"
              aria-current={n === page.page_number}
              key={page.id}
              onClick={() => setN(page.page_number)}
            >
              <span className="border border-solid border-accent rounded-xs overflow-hidden bg-paper block [box-shadow:0_0_0_2px_var(--accent-soft)]">
                <PageSheet page={page.page_number} src={page.render_uri} small />
              </span>
              <span className="font-semibold text-2xs font-mono text-accent mt-1 block">{page.page_number}</span>
            </Button>
          ))}
        </div>
        <div className="border-r border-solid border-r-line bg-sheet flex flex-col min-w-0 gap-3 p-4 max-[560px]:p-2">
          <div className="flex flex-wrap items-center gap-1">
            <span className="inline-flex items-center text-2xs font-semibold rounded-pill whitespace-nowrap bg-idle-soft text-idle gap-1 py-1 px-2">
              <i className="w-[6px] h-[6px] rounded-pill bg-current" />
              sayfa {n} / {pages.length}
            </span>
            <code className={technicalChip}>
              güven <b>{p?.confidence == null ? "ölçülmedi" : p.confidence.toFixed(2)}</b>
            </code>
            <code className={technicalChip}>{p?.parser ?? "bilinmiyor"}</code>
          </div>
          <PageSheet page={n} src={p?.render_uri} />
          <code className="font-mono text-2xs text-muted">{p?.render_uri}</code>
        </div>
        <div className="flex flex-col min-w-0 max-[1180px]:col-[1/-1] max-[1180px]:border-t max-[1180px]:border-solid max-[1180px]:border-t-line gap-3 p-4 max-[560px]:p-3">
          <div className="flex border-b border-solid border-b-line2 gap-1">
            <Button variant="ghost" className="h-auto whitespace-normal bg-transparent border-0 text-xs text-muted border-b-[2px] border-solid border-b-transparent [&[aria-selected='true']]:text-accent [&[aria-selected='true']]:border-b-accent [&[aria-selected='true']]:font-semibold py-1 px-2" aria-selected>
              Legacy extraction Markdown
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-1">
            {(p?.quality_flags ?? []).map((f) => (
              <span className="inline-flex items-center text-2xs font-semibold rounded-pill whitespace-nowrap bg-warn-soft text-warn gap-1 py-1 px-2" key={f}>
                <i className="w-[6px] h-[6px] rounded-pill bg-current" />
                {f.replace("-", " ")}
              </span>
            ))}
          </div>
          <div className="font-normal text-base leading-[1.62] font-serif text-ink max-w-[66ch] overflow-auto max-h-[56vh] [&_h2]:font-semibold [&_h2]:text-md [&_h2]:font-sans [&_h2]:mt-0 [&_h2]:mb-2 [&_p]:mt-0 [&_p]:mb-3 [&_table]:border-collapse [&_table]:font-normal [&_table]:text-xs [&_table]:font-sans [&_table]:mt-1 [&_table]:mb-3 [&_table]:w-full [&_th]:border [&_th]:border-solid [&_th]:border-line [&_th]:text-left [&_td]:border [&_td]:border-solid [&_td]:border-line [&_td]:text-left [&_th]:bg-sheet [&_th]:font-semibold [&_th]:text-2xs [&_h2]:mx-0 [&_p]:mx-0 [&_table]:mx-0 [&_th]:py-1 [&_th]:px-2 [&_td]:py-1 [&_td]:px-2">
            {markdown ? (
              <pre className="whitespace-pre-wrap font-doc text-base leading-doc wrap-anywhere">{markdown}</pre>
            ) : (
              <p>Bu sürüm için extraction Markdown mevcut değil. Demo modunda dosya üretilmez.</p>
            )}
          </div>
        </div>
      </section>
      <div className={technicalNote}>
        <b>Extraction önizlemesi:</b> Solda seçilen sayfa, sağda dokümanın tamamının
        Markdown çıktısı bulunur. Bu çıktı henüz canonical knowledge değildir.
        Sayfa hataları job kaydında tutulur; confidence ölçülmez. Canonical yapı ve evidence için Structure/Provenance sekmelerini kullanın.
      </div>
    </div>
  );
}
function VersionBox({ v, current }: { v: Version; current?: boolean }) {
  return (
    <div className="border border-solid border-line rounded-card bg-paper min-h-52 [&_h4]:mt-0 [&_h4]:mb-1 [&_h4]:text-sm [&_h4]:mx-0 p-3">
      <h4>
        {v.id}{" "}
        {current && (
          <span className="inline-flex items-center text-2xs font-semibold rounded-pill whitespace-nowrap ml-1 bg-ok-soft text-ok gap-1 py-1 px-2">
            <i className="w-[6px] h-[6px] rounded-pill bg-current" />
            güncel
          </span>
        )}
      </h4>
      <div className="font-normal text-2xs font-mono text-faint mb-3">
        {new Date(v.created_at).toLocaleDateString("tr-TR", {
          day: "2-digit",
          month: "short",
          year: "numeric",
        })}{" "}
        · {v.parser}
        {v.vision_provider ? ` · ${v.vision_provider}` : " · görsel model yok"}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-y-1 gap-x-4 text-xs [&_dt]:text-muted [&_dd]:font-normal [&_dd]:text-2xs [&_dd]:font-mono [&_dd]:text-ink2 [&_dd]:[word-break:break-all] [&_dd]:m-0">
        <dt>sayfa</dt>
        <dd>{v.page_count}</dd>
        <dt>durum</dt>
        <dd>{v.status}</dd>
      </dl>
    </div>
  );
}
function VersionsView({ versions }: { versions: Version[] }) {
  if (!versions.length) return <EmptyState title="Sürüm bilgisi yok" text="Bu doküman için sürüm kaydı alınamadı." />;
  const sorted = [...versions].sort((a, b) => a.revision - b.revision);
  return <div className={screenContent}>
    {sorted.map((v, i) => <VersionBox key={v.id} v={v} current={i === sorted.length - 1} />)}
    <div className={technicalNote}>Bunlar yüklenen kaynak dosyanın sürümleridir; içerik inceleme geçmişi değildir. Belge içeriğindeki inceleme kayıtları için “Belgeyi incele” sekmesindeki Revision geçmişi bölümüne bakın. Canonical revision kimliği Özet sekmesinde gösterilir. Live diff endpoint’i yalnızca legacy sayaç farkı verir.
      İçerik diff’i, Structured Knowledge Patch ve aynı dokümana yeni sürüm yükleme henüz uygulanmadı.</div>
  </div>;
}
function Detail({
  doc,
  tab,
  setTab,
  job,
  pages,
  versions,
  markdown,
  knowledge,
  knowledgeState,
  mode,
  onSaved,
  onDirtyChange,
}: {
  doc: DocumentRow;
  tab: DetailTab;
  setTab: (t: DetailTab) => void;
  job: Job | null;
  pages: Page[];
  versions: Version[];
  markdown: string;
  knowledge: Knowledge | null;
  knowledgeState: string;
  mode: Mode | null;
  onSaved: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const developerMode = useDeveloperMode();
  const canonical = knowledge?.snapshot;
  // Once opened, the review workspace stays mounted (hidden) so unsaved drafts survive tab switches.
  const [reviewOpened, setReviewOpened] = useState(tab === "review" || tab === "history");
  useEffect(() => { if (tab === "review" || tab === "history") setReviewOpened(true); }, [tab]);
  const canonicalUnavailable = <div className="pt-6 pb-12 flex flex-col min-w-0 [&_>_details]:border [&_>_details]:border-solid [&_>_details]:border-line [&_>_details]:rounded-sm [&_>_details]:bg-paper [&_>_details]:min-w-0 [&_>_details_summary]:cursor-pointer [&_>_details_summary]:font-normal [&_>_details_summary]:text-xs [&_>_details_summary]:font-mono max-[760px]:pt-4 max-[760px]:pb-8 px-8 gap-4 max-[760px]:px-4 [&_>_details_summary]:p-3"><div className="border border-dashed border-line rounded-lg bg-paper text-ink2 [&_strong]:font-semibold [&_strong]:text-md [&_strong]:font-sans [&_p]:mt-1 [&_p]:mb-0 [&_p]:text-muted [&_p]:text-xs py-10 px-6 [&_p]:mx-0"><strong>Belge içeriği henüz hazır değil</strong>
    <p>{developerMode ? knowledgeState : "Belge içeriği alınamadı. Bir süre sonra tekrar deneyin."}</p></div></div>;
  return (
    <Tabs value={tab} onValueChange={value => setTab(value as DetailTab)} className="min-w-0 flex-col gap-0">
      <DetailHead doc={doc} tab={tab} setTab={setTab} knowledge={knowledge} />
      <TabsContent value={tab} forceMount className="min-w-0">
      {(tab === "review" || tab === "history" || reviewOpened) && (
        <div hidden={tab !== "review" && tab !== "history"}>
          <ReviewWorkspace view={tab === "history" ? "history" : "read"} onRead={() => setTab("review")} documentId={doc.id} onSaved={onSaved} mode={mode} onDirtyChange={onDirtyChange} />
        </div>
      )}
      {tab === "ai-output" && (canonical ? <AIOutputView key={canonical.knowledge_revision.id} snapshot={canonical} versionId={doc.versionId} /> : canonicalUnavailable)}
      {tab === "overview" && (knowledge ? <CanonicalOverview knowledge={knowledge} status={doc.status} /> : canonicalUnavailable)}
      {tab === "structure" && (canonical ? <CanonicalStructure snapshot={canonical} versionId={doc.versionId} /> : canonicalUnavailable)}
      {tab === "tables" && (canonical ? <CanonicalTables snapshot={canonical} versionId={doc.versionId} /> : canonicalUnavailable)}
      {tab === "assets" && (canonical ? <CanonicalAssets snapshot={canonical} versionId={doc.versionId} /> : canonicalUnavailable)}
      {tab === "issues" && (canonical ? <CanonicalIssues snapshot={canonical} /> : canonicalUnavailable)}
      {tab === "provenance" && (canonical ? <ProvenanceView snapshot={canonical} versionId={doc.versionId} /> : canonicalUnavailable)}
      {tab === "raw" && (canonical ? <CanonicalRaw snapshot={canonical} /> : canonicalUnavailable)}
      {tab === "pipeline" && <Pipeline job={job} />}
      {tab === "pages" && (
        <PagesView pages={pages} markdown={markdown} />
      )}
      {tab === "versions" && <VersionsView versions={versions} />}
      </TabsContent>
    </Tabs>
  );
}

export default function Home() {
  const [workspace, setWorkspace] = useState<string>(DEFAULT_WORKSPACE);
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [screen, setScreen] = useState<Screen>("summary"),
    [tab, setTab] = useState<DetailTab>("review"),
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
    [versions, setVersions] = useState<Version[]>([]),
    [markdown, setMarkdown] = useState(""),
    [knowledge, setKnowledge] = useState<Knowledge | null>(null),
    [knowledgeState, setKnowledgeState] = useState(""),
    [uploadStates, setUploadStates] = useState<UploadState[]>([]),
    [toast, setToast] = useState("");
  const [developerMode, setDeveloperMode] = useState(false);
  const [reviewRefresh, setReviewRefresh] = useState(0);
  const [navigationKey, setNavigationKey] = useState(0);
  const [initialCollection, setInitialCollection] = useState<string>();
  const [focusedQuestionId, setFocusedQuestionId] = useState<string>();
  const [documentPollError, setDocumentPollError] = useState("");
  const [modelRefresh, setModelRefresh] = useState(0);
  const generation = useRef(0);
  const workspaceRef = useRef(workspace);
  const uploadController = useRef<AbortController | null>(null);
  const uploadQueue = useRef<ReturnType<typeof createUploadQueue<RegisterResponse>> | null>(null);
  const review = useWorkspaceReview(API, workspace, reviewRefresh);
  const informationJob = useRecordJob(API, workspace, mode, modelRefresh, () => { void review.reload(); });
  const transferBusy = uploadStates.some(item => ["waiting", "hashing", "registering", "uploading", "confirming"].includes(item.phase));
  const extractionReason = mode === "demo" ? "Örnek görünümde yükleme ve bilgi çıkarma kapalı."
    : mode !== "live" || loading ? "Bağlantı ve belgeler kontrol ediliyor."
    : error ? "Belgeler alınamadı. Bağlantıyı kontrol edip listeyi yenileyin."
    : documentPollError ? documentPollError
    : !informationJob.loaded ? "Bilgi işinin durumu kontrol ediliyor."
    : informationJob.starting || jobActive(informationJob.job) ? "Bilgi işi devam ediyor; aşamalar aşağıda gösteriliyor."
    : informationJob.modelState === "loading" ? "Model seçimi kontrol ediliyor."
    : informationJob.modelState === "error" ? "Model seçimi alınamadı. Ayarlar'ı açıp bağlantıyı kontrol edin."
    : informationJob.modelState !== "ready" ? "Bilgi çıkarmak için Ayarlar'dan model seçin ve etkinleştirin."
    : !docs.length ? "Önce belgelerinizi yükleyin."
    : transferBusy ? "Dosyaların yüklenmesi bitince bilgi çıkarabilirsiniz."
    : uploadStates.some(item => item.phase === "error") ? "Yüklenemeyen dosyayı yeniden deneyin; tüm belgeler hazır olmalı."
    : docs.some(document => document.status === "partial") ? "Bazı belgeler kısmi hazır. Belgeleri açıp eksik içeriği kontrol edin; tüm belgeler hazır olmalı."
    : docs.some(document => document.status === "failed") ? "Bazı belgeler hazırlanamadı. Belgeleri açıp sorunu kontrol edin; tüm belgeler hazır olmalı."
    : docs.some(document => document.status !== "done") ? "Belgeler hazırlanıyor. Tümü hazır olduğunda bilgi çıkarabilirsiniz."
    : "";
  useEffect(() => {
    try { setDeveloperMode(localStorage.getItem("docgrain.developer-mode") === "true"); } catch { /* Storage may be unavailable. */ }
  }, []);
  function toggleDeveloperMode() {
    const next = !developerMode;
    setDeveloperMode(next);
    try { localStorage.setItem("docgrain.developer-mode", String(next)); } catch { /* Keep the switch usable without storage. */ }
    if (!next) {
      if (["jobs", "providers", "contract"].includes(screen)) setScreen("summary");
      if (tab !== "review" && tab !== "history") setTab("review");
    }
  }
  const requestId = useRef(0);
  const dirtyRef = useRef(false);

  async function refresh(targetWs = workspace) {
    const request = ++requestId.current;
    setLoading(true); setError(""); setDocumentPollError(""); setMode(null);
    setReviewRefresh(value => value + 1);
    setDocs([]); setJobs([]); setProviders([]);
    setSelected(null); setScreen((prev) => (prev === "detail" ? "documents" : prev));
    try {
      const health = await apiJson<{ mode: Mode }>(`${API}/healthz`);
      if (request !== requestId.current) return;
      if (health.mode !== "live" && health.mode !== "demo") throw new Error("API çalışma modu doğrulanamadı.");
      const [documentResult, jobResult, providerResult, workspaceResult] = await Promise.allSettled([
        readDocuments(targetWs, health.mode),
        apiJson<Job[]>(`${API}/v1/jobs`, undefined, health.mode),
        apiJson<Provider[]>(`${API}/v1/providers/health`, undefined, health.mode),
        apiJson<WorkspaceItem[]>(`${API}/v1/workspaces`, undefined, health.mode).catch(() => [] as WorkspaceItem[]),
      ]);
      if (request !== requestId.current) return;
      setMode(health.mode);
      const documents = documentResult.status === "fulfilled" ? documentResult.value : [];
      const nextWorkspaces = workspaceResult.status === "fulfilled" ? workspaceResult.value : [];
      setDocs(documents.map(documentRow));
      setJobs(jobResult.status === "fulfilled" ? jobResult.value : []);
      setProviders(providerResult.status === "fulfilled" ? providerResult.value : []);
      if (documentResult.status === "rejected") setError("Belgeler alınamadı.");

      // Ensure active workspace and default workspace are represented in the list
      const wsMap = new Map<string, WorkspaceItem>();
      for (const w of nextWorkspaces) {
        wsMap.set(w.id, w);
      }
      if (!wsMap.has(targetWs)) {
        wsMap.set(targetWs, { id: targetWs, documents: documents.length });
      }
      if (!wsMap.has(DEFAULT_WORKSPACE)) {
        wsMap.set(DEFAULT_WORKSPACE, { id: DEFAULT_WORKSPACE, documents: 0 });
      }
      const combinedWorkspaces = Array.from(wsMap.values()).map(item => ({ ...item, documents: item.id === targetWs ? documents.length : item.documents }));
      setWorkspaces(combinedWorkspaces);
    } catch (cause) {
      if (request === requestId.current) setError(`API verileri alınamadı: ${String(cause)}`);
    } finally {
      if (request === requestId.current) setLoading(false);
    }
  }

  function handleWorkspaceChange(nextWs: string) {
    if (nextWs === workspace) return;
    if (!confirmDiscard()) return;
    generation.current += 1; workspaceRef.current = nextWs;
    uploadController.current?.abort(); uploadQueue.current = null;
    setWorkspace(nextWs); setScreen("documents"); setToast("");
    setSelected(null); setJob(null); setPages([]); setVersions([]); setKnowledge(null); setMarkdown("");
    setDetailLoading(false); setDetailError(""); dirtyRef.current = false;
    setInitialCollection(undefined); setFocusedQuestionId(undefined);
    setUploadStates([]); setDocumentPollError("");
    try {
      localStorage.setItem("docgrain.workspace_id", nextWs);
    } catch {
      /* Storage may be unavailable. */
    }
    void refresh(nextWs);
  }

  useEffect(() => {
    let savedWorkspace = DEFAULT_WORKSPACE;
    try { savedWorkspace = localStorage.getItem("docgrain.workspace_id") || DEFAULT_WORKSPACE; }
    catch { /* The default remains available without storage. */ }
    workspaceRef.current = savedWorkspace;
    if (savedWorkspace !== DEFAULT_WORKSPACE) setWorkspace(savedWorkspace);
    void refresh(savedWorkspace);
    return () => { requestId.current += 1; generation.current += 1; uploadController.current?.abort(); };
  }, []);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 4000);
    return () => clearTimeout(id);
  }, [toast]);
  useEffect(() => { window.scrollTo({ top: 0, behavior: "auto" }); }, [screen, tab, selected?.id]);

  // Unsaved review drafts are reported by ReviewWorkspace; leaving the document asks first.
  function confirmDiscard() {
    return !dirtyRef.current || window.confirm("Kaydedilmemiş taslak değişiklikler silinecek. Devam etmek istiyor musunuz?");
  }
  // silent: refresh knowledge and the list row after a review save without resetting the view,
  // tab, or the mounted review workspace. The document's source version is never changed here.
  async function open(d: DocumentRow, options?: { silent?: boolean }) {
    const silent = options?.silent === true;
    const request = ++requestId.current;
    if (!silent) {
      setSelected(d); setTab("review"); setScreen("detail");
      setJob(null); setPages([]); setVersions([]); setMarkdown("");
      setKnowledge(null); setKnowledgeState("");
      setDetailError(""); setDetailLoading(true);
    }
    try {
      if (!mode) throw new Error("API modu doğrulanamadı.");
      const [canonicalResult, jobResult, pagesResult, versionsResult, markdownResult, rowResult] = await Promise.allSettled([
        apiJson<Knowledge>(`${API}/v1/documents/${d.id}/knowledge`, undefined, mode),
        d.jobId ? apiJson<Job>(`${API}/v1/jobs/${d.jobId}`, undefined, mode) : Promise.resolve(null),
        d.versionId ? apiJson<Page[]>(`${API}/v1/versions/${d.versionId}/pages`, undefined, mode) : Promise.resolve([]),
        apiJson<Version[]>(`${API}/v1/documents/${d.id}/versions`, undefined, mode),
        mode === "live" && d.versionId ? fetch(`${API}/v1/documents/${d.id}/versions/${d.versionId}/artifacts/document.md`).then(async (response) => {
          if (response.headers.get("X-Docgrain-Mode") !== "live") throw new Error("API modu değişti; listeyi yenileyin.");
          return response.ok ? response.text() : "";
        }) : Promise.resolve(""),
        silent && mode === "live" ? apiJson<DocumentListResponse>(`${API}/v1/documents/${d.id}`, undefined, mode) : Promise.resolve(null),
      ]);
      if (request !== requestId.current) return;
      if (rowResult.status === "fulfilled" && rowResult.value) {
        const fresh = documentRow(rowResult.value);
        setDocs((current) => current.map((row) => row.id === fresh.id
          ? { ...fresh, versionId: row.versionId, version: row.version } : row));
      }
      setKnowledge(canonicalResult.status === "fulfilled" ? canonicalResult.value : null);
      setKnowledgeState(canonicalResult.status === "rejected" ?
        (mode === "demo" ? "Demo modunda canonical snapshot üretilmez." :
          canonicalResult.reason instanceof HttpError && canonicalResult.reason.status === 404 ?
            (canonicalResult.reason.message.includes("unavailable") ? "Canonical storage unavailable." : "Bu doküman için henüz canonical revision üretilmedi.") :
            `Canonical snapshot okunamadı: ${String(canonicalResult.reason)}`) : "");
      setJob(jobResult.status === "fulfilled" ? jobResult.value : null);
      setPages(pagesResult.status === "fulfilled" ? (mode === "demo" ? pagesResult.value.map((page) => ({ ...page, render_uri: "" })) : pagesResult.value) : []);
      setVersions(versionsResult.status === "fulfilled" ? versionsResult.value : []);
      setMarkdown(markdownResult.status === "fulfilled" ? markdownResult.value : "");
    } catch (cause) {
      if (request !== requestId.current) return;
      if (silent) setToast(`Doküman bilgileri yenilenemedi: ${String(cause)}`);
      else setDetailError(String(cause));
    } finally {
      if (!silent && request === requestId.current) setDetailLoading(false);
    }
  }
  async function createWorkspace(name: string) {
    if (mode !== "live" || !confirmDiscard()) return false;
    const epoch = generation.current;
    const result = await apiJson<WorkspaceItem>(`${API}/v1/workspaces`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }),
    }, "live");
    if (epoch !== generation.current) return false;
    setWorkspaces(previous => [...previous.filter(item => item.id !== result.id), result]);
    dirtyRef.current = false;
    handleWorkspaceChange(result.id);
    return true;
  }
  function upload(files: File[]) {
    if (mode !== "live") return;
    if (!uploadQueue.current) {
      const epoch = generation.current;
      const controller = new AbortController(); uploadController.current = controller;
      uploadQueue.current = createUploadQueue<RegisterResponse>({
        apiUrl: API, workspaceId: workspace, fetch, hash: sha256, signal: controller.signal,
        active: () => epoch === generation.current,
        onState: state => setUploadStates(previous => previous.some(item => item.id === state.id)
          ? previous.map(item => item.id === state.id ? state : item) : [...previous, state]),
        onRegistered: registration => {
          const row = documentRow({ document: registration.document, latest_version: registration.version, latest_job_id: registration.job_id });
          setDocs(previous => [row, ...previous.filter(item => item.id !== row.id)]);
        },
        onUploaded: () => { /* The independent document poll follows preparation. */ },
      });
    }
    uploadQueue.current.add(files);
  }
  useEffect(() => {
    if (mode !== "live") return;
    const epoch = generation.current;
    const controller = new AbortController();
    let reading = false;
    const active = () => !controller.signal.aborted && epoch === generation.current && workspaceRef.current === workspace;
    async function pollDocuments() {
      if (reading || !active()) return;
      reading = true;
      try {
        const [documentResult, jobResult] = await Promise.allSettled([
          readDocuments(workspace, "live", controller.signal),
          apiJson<Job[]>(`${API}/v1/jobs`, { signal: controller.signal, cache: "no-store" }, "live"),
        ]);
        if (documentResult.status === "rejected") throw documentResult.reason;
        const rows = documentResult.value.map(documentRow);
        if (jobResult.status === "fulfilled") {
          const currentJobs = jobResult.value.filter(item => rows.some(row => row.jobId === item.id));
          for (const row of rows) {
            const preparation = currentJobs.find(item => item.id === row.jobId);
            if (["processing", "running", "queued", "pending"].includes(row.status) && preparation && ["queued", "running", "partial", "failed"].includes(preparation.status)) row.status = preparation.status;
          }
          if (active()) setJobs(currentJobs);
        }
        if (!active()) return;
        setDocumentPollError(jobResult.status === "rejected" ? "Belge hazırlığının durumu alınamadı. Bağlantıyı kontrol edin; tekrar kontrol ediliyor." : "");
        setDocs(previous => {
          // Registrations may finish while a list request is in flight. Keep those rows until the next poll.
          const known = new Set(rows.map(row => row.id));
          return [...rows, ...previous.filter(row => !known.has(row.id))];
        });
        setUploadStates(previous => previous.map(item => {
          if (["error", "waiting", "hashing", "registering", "uploading", "confirming"].includes(item.phase)) return item;
          const row = rows.find(row => row.jobId === item.jobId);
          if (!row) return item;
          const phase = row.status === "processing" ? "running" : row.status;
          return { ...item, phase: phase as UploadState["phase"], message: documentStatusLabel(row.status) };
        }));
        setWorkspaces(previous => previous.map(item => item.id === workspace ? { ...item, documents: rows.length } : item));
      } catch { if (active()) setDocumentPollError("Belge durumları alınamadı. Bağlantıyı kontrol edin; tekrar kontrol ediliyor."); }
      finally { reading = false; }
    }
    const timer = setInterval(() => { void pollDocuments(); }, 2000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [workspace, mode]);

  return (
    <DeveloperModeContext.Provider value={developerMode}>
    <div className="min-h-dvh text-base md:grid md:grid-cols-[244px_minmax(0,1fr)] motion-reduce:[&_*]:animate-none motion-reduce:[&_*]:transition-none">
      <Sidebar
        developerMode={developerMode}
        toggleDeveloperMode={toggleDeveloperMode}
        screen={screen}
        nav={(next) => {
          if (!confirmDiscard()) return;
          setInitialCollection(undefined); setFocusedQuestionId(undefined);
          setNavigationKey(value => value + 1); setScreen(next);
        }}
        questionCount={review.questionState === "ready" ? review.total : undefined}
        busy={review.busy || transferBusy}
        docs={docs.length}
        jobs={jobs.filter((j) => j.status === "running").length}
        workspace={workspace}
        workspaces={workspaces}
        onWorkspaceChange={handleWorkspaceChange}
        readOnly={mode !== "live"}
        onCreateWorkspace={createWorkspace}
      />
      <main className="flex min-w-0 flex-col">
        {(developerMode || mode === "demo" || screen === "documents" || screen === "detail") && <div className="bg-transparent border-b border-solid border-b-line flex items-center justify-between text-xs max-[780px]:flex-wrap text-muted py-3 gap-4 px-4 md:px-6 xl:px-10" role="status">
          <span>{mode === "demo" ? "Örnek belgeleri görüntülüyorsunuz. Düzenleme ve yükleme kapalı."
            : mode === "live" ? "Belgelerinizi kaynaklarıyla birlikte inceleyebilirsiniz." : "Bağlantı kuruluyor…"}</span>
          <Button variant="ghost" className="h-auto whitespace-normal border border-solid border-line bg-paper rounded-lg font-medium text-ink2 inline-flex items-center [&:hover]:border-line-strong [&:hover]:bg-sheet [&:hover]:text-ink [&:disabled]:cursor-not-allowed [&:disabled]:opacity-[.55] [&:disabled]:bg-idle-soft [&:disabled]:border-line [&:disabled]:text-muted [&:disabled:hover]:cursor-not-allowed [&:disabled:hover]:opacity-[0.58] [&:disabled:hover]:bg-idle-soft [&:disabled:hover]:border-line [&:disabled:hover]:text-muted motion-safe:transition-colors motion-safe:duration-150 justify-center text-xs min-h-[var(--control-height-sm)] gap-1 py-1 px-2" onClick={() => { if (confirmDiscard()) void refresh(workspace); }} disabled={loading || review.busy || transferBusy}>Listeyi yenile</Button>
        </div>}
        {screen === "summary" ? <SummaryView companyName={formatWorkspaceName(workspace, workspaces.find(item => item.id === workspace)?.name)} review={review} readOnly={mode !== "live"}
          onCollections={key => { setInitialCollection(key); setScreen("collections"); }}
          onQuestions={() => { setFocusedQuestionId(undefined); setScreen("questions"); }}
          onDocuments={() => setScreen("documents")} />
          : screen === "questions" ? <QuestionsView key={`${workspace}:${navigationKey}`} review={review} readOnly={mode !== "live"} focusedId={focusedQuestionId} onCollections={() => { setInitialCollection(undefined); setScreen("collections"); }} />
          : screen === "collections" ? <InformationView key={`${workspace}:${navigationKey}`} apiUrl={API} workspaceId={workspace} initialCollection={initialCollection}
            revisionId={review.summary?.revision_id} fieldLabels={review.fieldLabels}
            documentNames={Object.fromEntries(docs.map(document => [document.id, document.title || document.file]))}
            summaries={review.summary?.collections ?? []} questions={review.questions} questionState={review.questionState}
            onQuestion={question => { setFocusedQuestionId(question.id); review.revisit(); setScreen("questions"); }} />
          : screen === "settings" || screen === "try" ? mode === null ? <div role={error ? "alert" : "status"}>
              <EmptyState title={error ? "Bağlantı kurulamadı" : "Bağlanıyor"} text={error ? "Çalışma alanı alınamadı. Bağlantıyı kontrol edip yeniden deneyin." : "Çalışma alanı kontrol ediliyor."} />
              {error && <div className={pageGutter}><Button variant="outline" onClick={() => void refresh(workspace)}>Tekrar dene</Button></div>}
            </div> : screen === "settings" ? <WorkspaceSettings key={workspace} apiUrl={API} workspaceId={workspace} mode={mode} onSaved={() => setModelRefresh(value => value + 1)} />
              : <TryView key={`${workspace}:${review.summary?.revision_id ?? "empty"}`} apiUrl={API} workspaceId={workspace} mode={mode} /> : loading ? <EmptyState title="Yükleniyor" text="Belgeleriniz alınıyor." />
          : error ? <div role="alert"><EmptyState title="Bağlantı kurulamadı" text={developerMode ? error : "Belgeler alınamadı. Bağlantıyı kontrol edip listeyi yenileyin."} /></div>
          : screen === "documents" ? (
          <Documents
            docs={docs}
            open={(d) => { if (confirmDiscard()) void open(d); }}
            upload={upload}
            uploadStates={uploadStates}
            retryUpload={id => uploadQueue.current?.retry(id)}
            extraction={{ enabled: !extractionReason, reason: extractionReason, start: () => { void informationJob.start(!extractionReason); }, settings: () => setScreen("settings"), job: informationJob.job, error: informationJob.error, starting: informationJob.starting, showSettings: mode === "live" && ["off", "error"].includes(informationJob.modelState) }}
            mode={mode}
          />
        ) : screen === "jobs" ? (
          <Jobs jobs={jobs} docs={docs} />
        ) : screen === "providers" ? (
          <Providers items={providers} />
        ) : screen === "contract" ? (
          <Contract />
        ) : detailLoading ? <EmptyState title="Yükleniyor" text="Belge alınıyor." />
          : detailError ? <div role="alert"><EmptyState title="Belge okunamadı" text={developerMode ? detailError : "Belge alınamadı. Listeyi yenileyip tekrar deneyin."} /></div>
          : selected ? (
          <Detail
            key={selected.id}
            doc={selected}
            tab={tab}
            setTab={setTab}
            job={job}
            pages={pages}
            versions={versions}
            markdown={markdown}
            knowledge={knowledge}
            knowledgeState={knowledgeState}
            mode={mode}
            onSaved={() => void open(selected, { silent: true })}
            onDirtyChange={(dirty) => { dirtyRef.current = dirty; }}
          />
        ) : null}
      </main>
      {toast && (
        <div role="status" className="fixed max-w-[calc(100vw-32px)] wrap-anywhere right-4 bottom-4 bg-accent text-on-accent border border-solid border-accent-line rounded-lg shadow-2 text-xs z-[99] motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300 [&_i]:inline-block [&_i]:w-[7px] [&_i]:h-[7px] [&_i]:rounded-pill [&_i]:bg-ok [&_i]:mr-2 py-2 px-3">
          <i />
          {developerMode || !toast.includes("yüklenemedi") && !toast.includes("yenilenemedi") ? toast : "İşlem tamamlanamadı. Bağlantıyı kontrol edip tekrar deneyin."}
        </div>
      )}
    </div>
    </DeveloperModeContext.Provider>
  );
}
