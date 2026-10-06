"use client";

import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";


import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { useDeveloperMode } from "../developer-mode";
import { RevisionChat } from "./revision-chat";
import { EvidenceView, type Cell, type Evidence, type Locator, type Node, type Snapshot } from "./inspector";
import { LocalVisualProposal, type LocalVisualProposalData } from "./local-visual-proposal";


const documentProse = "font-normal text-md leading-[1.75] font-serif whitespace-pre-wrap wrap-anywhere [&_mark]:bg-warn-soft [&_mark]:text-inherit [&_mark]:rounded-xs max-[640px]:text-base [&_mark]:py-0 [&_mark]:px-1 m-0";
const sourceAction = "h-auto min-h-7 whitespace-normal bg-transparent border-0 text-xs font-semibold text-accent [text-decoration:underline] [text-underline-offset:3px] [&:disabled]:opacity-[.45] py-1 px-0";
const reviewAction = "h-auto min-h-7 whitespace-normal inline-flex items-center justify-center border border-solid border-line rounded-sm bg-paper text-ink text-xs font-semibold no-underline cursor-pointer motion-safe:transition-colors motion-safe:duration-150 [&:hover:not(:disabled)]:border-accent [&:hover:not(:disabled)]:bg-accent-soft [&:disabled]:opacity-[.45] [&:disabled]:cursor-default gap-1 py-2 px-3";
const loadingWorkspace = "text-ink min-w-0 pt-6 pb-12 flex flex-col items-start [&_:focus-visible]:[outline:2px_solid_var(--accent)] [&_:focus-visible]:[outline-offset:2px] max-[1000px]:pt-4 max-[1000px]:pb-8 px-8 gap-3 max-[1000px]:px-4";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Mode = "live" | "demo";
type Scalar = string | number | boolean | null;
type Draft = string | boolean;
type ReviewField = {
  field_id: string; node_id: string; kind: "text" | "table_cell" | "description"; label: string;
  value: Scalar; evidence_ids: string[]; editable: boolean; blocked_reason: string | null;
};
type HistoryEntry = {
  revision_id: string; parent_revision_id: string | null; created_at: string;
  kind: "extraction" | "manual_review"; reviewer_id: string | null; reason: string | null;
};
type Workspace = {
  document_id: string; latest_revision_id: string; approved_revision_id: string | null; snapshot_sha256: string;
  can_edit: boolean; snapshot: Snapshot;
  source: { filename: string; mime_type: string; download_url: string; document_version_id: string | null;
    pages: { page_number: number; render_url: string }[] };
  fields: ReviewField[]; history: HistoryEntry[]; warnings: string[];
};
type ChangeBody = { field_id: string; before: Scalar; after: Scalar; visual_uncertainties?: string[] };
type RequestBody = {
  base_revision_id: string; base_snapshot_sha256: string; operation_id: string; occurred_at: string;
  reviewer_id: string; reason: string; changes: ChangeBody[];
};
type Preview = {
  proposal_id: string; base_revision_id: string; snapshot_sha256: string; review_status: string;
  changes: { field_id: string; node_id: string; kind: ReviewField["kind"]; label: string; before: Scalar; after: Scalar; evidence_ids: string[]; visual_uncertainties?: string[] | null }[];
  warnings: string[];
};
type SaveResult = { revision_id: string; parent_revision_id: string | null; inserted: boolean;
  latest_revision_id: string; approved_revision_id: string | null; output_published: boolean };
type PreviewState =
  | { status: "idle" } | { status: "loading" } | { status: "error"; message: string }
  | { status: "ready"; data: Preview; body: RequestBody };
type SaveState = { status: "idle" | "saving" | "error" | "saved"; message: string };
type Selection = { nodeId: string; fieldId?: string; evidenceId?: string };
type SectionKey = "text" | "tables" | "visuals" | "gaps" | "history" | "chat";
type ReadBlock = { node: Node; depth: number; trail: string[] };
type GridSlot = { cell: Cell; field: ReviewField | null; covered: boolean };
type Grid = { rows: GridSlot[][]; loose: ReviewField[] };
type Gap = { key: string; title: string; detail: string; nodeId?: string; count: number };
type Adoption = { proposal: LocalVisualProposalData; description: string; adopted_at: string };

class HttpError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

const SECTIONS: [SectionKey, string][] = [
  ["text", "Metin"], ["tables", "Tablolar"], ["visuals", "Görseller"], ["gaps", "Eksikler"], ["history", "Düzenleme geçmişi"], ["chat", "Belgeye sor"],
];
const KIND_LABEL: Record<ReviewField["kind"], string> = { text: "Metin", table_cell: "Tablo hücresi", description: "Görsel açıklaması" };
const KIND_SECTION: Record<ReviewField["kind"], SectionKey> = { text: "text", table_cell: "tables", description: "visuals" };
const DISCARD_MESSAGE = "Kaydedilmemiş taslak değişiklikler silinecek. Devam etmek istiyor musunuz?";

const norm = (text: string) => text.toLocaleLowerCase("tr-TR");
const absolute = (url: string) => /^https?:\/\//i.test(url) ? url : `${API}${url.startsWith("/") ? "" : "/"}${url}`;
const dateText = (value: string) => new Date(value).toLocaleString("tr-TR", {
  day: "2-digit", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit",
});
const toRaw = (value: Scalar): Draft => value === null ? "" : typeof value === "boolean" ? value : String(value);
const formatScalar = (value: Scalar) => value === null ? "(boş)" : value === "" ? "(boş metin)" :
  typeof value === "boolean" ? (value ? "Doğru" : "Yanlış") : String(value);
const looseText = (value: unknown) => value == null ? "" : typeof value === "string" ? value :
  typeof value === "number" || typeof value === "boolean" ? String(value) : JSON.stringify(value);

function describeDetail(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : "").filter(Boolean);
    return parts.length ? parts.join(" · ") : undefined;
  }
  return undefined;
}
async function request<T>(url: string, mode: Mode, init: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const served = response.headers.get("X-Docgrain-Mode");
  if (served && served !== mode) throw new Error("API çalışma modu değişti. Sayfayı yenileyip tekrar deneyin.");
  if (!response.ok) {
    let detail = `İstek tamamlanamadı (${response.status}).`;
    try { detail = describeDetail((await response.json())?.detail) ?? detail; } catch { /* non-JSON error body */ }
    throw new HttpError(response.status, detail);
  }
  return response.json() as Promise<T>;
}
const isWorkspace = (value: unknown): value is Workspace => {
  const item = value as Partial<Workspace> | null;
  return !!item && typeof item === "object" && !!item.snapshot && Array.isArray(item.snapshot.structure) &&
    Array.isArray(item.fields) && Array.isArray(item.history) && !!item.source && typeof item.snapshot_sha256 === "string";
};

type Computed = { ok: true; value: Scalar; changed: boolean } | { ok: false; error: string };
function compute(field: ReviewField, raw: Draft): Computed {
  const before = field.value;
  if (typeof before === "boolean") {
    return typeof raw === "boolean" ? { ok: true, value: raw, changed: raw !== before } : { ok: false, error: "Doğru veya Yanlış seçin." };
  }
  if (typeof raw !== "string") return { ok: false, error: "Geçersiz değer." };
  if (typeof before === "number") {
    const text = raw.trim();
    const normalized = /^-?\d+,\d+$/.test(text) ? text.replace(",", ".") : text;
    if (!/^-?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(normalized)) return { ok: false, error: "Bu alan sayı olmalı; metin veya boş değer kaydedilemez." };
    const value = Number(normalized);
    if (!Number.isFinite(value)) return { ok: false, error: "Geçerli bir sayı girin." };
    if (/^-?\d+$/.test(normalized) && !Number.isSafeInteger(value)) return { ok: false, error: "Sayı güvenle saklanamayacak kadar büyük." };
    return { ok: true, value, changed: value !== before };
  }
  return { ok: true, value: raw, changed: raw !== (before ?? "") };
}
const sameScalar = (a: unknown, b: unknown) => typeof a === typeof b && Object.is(a, b);

function nodeEvidenceIds(node: Node): string[] {
  return Array.from(new Set([
    ...node.annotation.provenance.evidence_ids,
    ...Object.values(node.field_annotations).flatMap((item) => item.provenance.evidence_ids),
    ...(node.rows ?? []).flatMap((row) => row.flatMap((cell) => cell.annotation?.provenance.evidence_ids ?? [])),
  ]));
}
function locatorLabel(locator: Locator): string {
  switch (locator.kind) {
    case "pdf_page": return `Sayfa ${locator.page_number}${locator.bbox ? "" : " (bölge bilinmiyor)"}`;
    case "image_region": return "Görseldeki bölge";
    case "docx_block": return `Word belgesi · ${locator.path}`;
    case "text_span": return `Metin dosyası · ${locator.start}–${locator.end}. karakter`;
    case "spreadsheet_range": return `Tablo sayfası “${locator.sheet}” · ${locator.a1_range}`;
    case "artifact_object": return "Çıkarılan dosya";
  }
}
const nodeTitle = (node: Node, fallback: string) => node.caption || node.title || node.heading || fallback;

function readingOrder(snapshot: Snapshot, nodes: Map<string, Node>): ReadBlock[] {
  const out: ReadBlock[] = [];
  const seen = new Set<string>();
  const markAll = (id: string) => {
    const node = nodes.get(id);
    if (!node || seen.has(id)) return;
    seen.add(id);
    (node.children ?? []).forEach(markAll);
  };
  const walk = (id: string, depth: number, trail: string[]) => {
    const node = nodes.get(id);
    if (!node || seen.has(id)) return;
    seen.add(id);
    if (node.kind !== "document") out.push({ node, depth, trail });
    if (node.kind === "list") { (node.children ?? []).forEach(markAll); return; }
    const next = node.kind === "section" ? [...trail, node.heading || node.title || "Bölüm"] : trail;
    (node.children ?? []).forEach((child) => walk(child, node.kind === "document" ? depth : depth + 1, next));
  };
  walk(snapshot.root_node_id, 0, []);
  for (const node of snapshot.structure) {
    if (!seen.has(node.id) && ["text_block", "list", "table", "asset", "chart"].includes(node.kind)) {
      seen.add(node.id);
      out.push({ node, depth: 0, trail: [] });
    }
  }
  return out;
}
function buildGrid(node: Node, fields: ReviewField[]): Grid {
  const cellFields = fields.filter((field) => field.kind === "table_cell");
  const rows: GridSlot[][] = (node.rows ?? []).map((row) => row.map((cell) => ({
    cell, field: null, covered: Boolean(cell.source_attributes?.merge_covered),
  })));
  rows.forEach((row, r) => row.forEach((slot, c) => {
    for (let rr = r; rr < Math.min(rows.length, r + slot.cell.row_span); rr++) {
      for (let cc = c; cc < Math.min(rows[rr].length, c + slot.cell.col_span); cc++) {
        if (rr !== r || cc !== c) rows[rr][cc].covered = true;
      }
    }
  }));
  const slots = rows.flat();
  const live = slots.filter((slot) => !slot.covered);
  const target = cellFields.length === slots.length ? slots : cellFields.length === live.length ? live : null;
  if (!cellFields.length) return { rows, loose: [] };
  if (!target) return { rows, loose: cellFields };
  target.forEach((slot, index) => { slot.field = cellFields[index]; });
  // The grid mapping is only trusted when every editable value agrees with the cell it was mapped to.
  if (target.some((slot) => slot.field?.editable && !sameScalar(slot.field.value, slot.cell.value))) {
    target.forEach((slot) => { slot.field = null; });
    return { rows, loose: cellFields };
  }
  return { rows, loose: [] };
}
const slotText = (slot: GridSlot, drafts: Record<string, Draft>) => {
  if (slot.field) {
    const raw = drafts[slot.field.field_id] ?? toRaw(slot.field.value);
    return typeof raw === "boolean" ? (raw ? "Doğru" : "Yanlış") : raw;
  }
  return slot.cell.display_text ?? looseText(slot.cell.value);
};
const defaultHeader = (grid: Grid) => grid.rows.length > 1 && grid.rows[0].every((slot) => {
  if (slot.covered) return true;
  const text = looseText(slot.cell.display_text ?? slot.cell.value).trim();
  return text !== "" && Number.isNaN(Number(text.replace(",", ".")));
});

const ISSUE_TEXT: Record<string, [string, string]> = {
  ocr_needs_review: ["Görselden okunan metin kaynakla doğrulanmadı", "Görselden okunan metni sayı ve Türkçe karakterler açısından kaynakla karşılaştırın."],
  ocr_low_confidence: ["Görselden okunan metin belirsiz", "Bazı satırların tanıma puanı düşük; özgün görselle karşılaştırın."],
  no_ocr_text: ["Görselde metin bulunamadı", "Özgün dosya korundu; görselin anlamı yorumlanmadı."],
  native_table_reconciled: ["Tablo kaynak geometrisiyle karşılaştırıldı", "Farklı okunan değerler korundu; kaynakla kontrol edin."],
  table_grid_conflict: ["Tablo yapısı çelişiyor", "Satır veya sütun sayısı okuyucular arasında uyuşmuyor; tablo yeniden şekillendirilmedi."],
  table_boundary_text_review: ["Hücre sınırında metin var", "Kırpılmış veya taşan kelimeler olabilir; başlığı kaynakta kontrol edin."],
  chart_visual_unverified: ["Grafik verisi korundu, görünümü doğrulanmadı", "Seri ve hücre verisi çıkarıldı; görsel yorum henüz doğrulanmadı."],
  unextracted_picture: ["Görsel tespit edildi ancak çıkarılamadı", "Dosyası alınamadığı için önizleme yok."],
  missing_visual_description: ["Görsel açıklaması eksik", "Görselin anlamı henüz metne aktarılmadı."],
};

type Ctx = {
  nodes: Map<string, Node>; fieldsByNode: Map<string, ReviewField[]>;
  viewLatest: boolean; wsEditable: boolean; locked: boolean;
  drafts: Record<string, Draft>; query: string; selection: Selection | null;
  uncertaintyDrafts: Record<string, string>; setUncertaintyDraft: (field: ReviewField, value: string) => void;
  setDraft: (field: ReviewField, value: Draft) => void; revert: (field: ReviewField) => void;
  mode: Mode | null; snapshotSha256: string;
  adoptProposal: (field: ReviewField, description: string, proposal: LocalVisualProposalData) => boolean;
  select: (selection: Selection, reveal?: boolean) => void;
  openSection: (section: SectionKey, nodeId?: string) => void;
};
const RwContext = createContext<Ctx | null>(null);
function useCtx(): Ctx {
  const value = useContext(RwContext);
  if (!value) throw new Error("ReviewWorkspace context missing");
  return value;
}
function fieldState(c: Ctx, field: ReviewField | null) {
  if (!field) return null;
  const draft = c.drafts[field.field_id];
  const result = draft === undefined ? null : compute(field, draft);
  let editable = true, reason = "";
  if (!c.viewLatest) { editable = false; reason = "Eski düzenleme · yalnızca okunabilir"; }
  else if (!c.wsEditable) { editable = false; reason = "Bu belge şu an düzenlemeye kapalı"; }
  else if (!field.editable) { editable = false; reason = field.blocked_reason || "Bu alan düzenlenemez"; }
  return {
    field, raw: draft ?? toRaw(field.value), editable, reason,
    changed: !!result && result.ok && result.changed,
    error: result && !result.ok ? result.error : "",
  };
}

function Highlight({ text, query }: { text: string; query: string }) {
  const needle = norm(query.trim());
  const hay = norm(text);
  if (!needle || hay.length !== text.length) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  let at = 0, hit = hay.indexOf(needle);
  while (hit !== -1) {
    if (hit > at) parts.push(text.slice(at, hit));
    parts.push(<mark key={hit}>{text.slice(hit, hit + needle.length)}</mark>);
    at = hit + needle.length;
    hit = hay.indexOf(needle, at);
  }
  parts.push(text.slice(at));
  return <>{parts}</>;
}
function AccessChip({ editable, reason }: { editable: boolean; reason: string }) {
  const developerMode = useDeveloperMode();
  if (editable && !developerMode) return null;
  return editable ? <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-accent-soft text-accent py-1 px-2">Düzenlenebilir</span>
    : <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-sheet text-faint py-1 px-2" title={reason}>Salt okunur · {reason}</span>;
}
function Original({ value }: { value: Scalar }) {
  return <div className="mt-2 bg-warn-soft border-l-[3px] border-solid border-l-warn rounded-xs [&_span]:block [&_span]:font-bold [&_span]:text-2xs [&_span]:font-mono [&_span]:tracking-[.1em] [&_span]:uppercase [&_span]:text-warn [&_p]:mt-1 [&_p]:mb-0 [&_p]:font-normal [&_p]:text-sm [&_p]:leading-[1.6] [&_p]:font-serif [&_p]:line-through [&_p]:[text-decoration-color:var(--warn-line)] [&_p]:whitespace-pre-wrap [&_p]:wrap-anywhere py-2 px-3 [&_p]:mx-0"><span>Orijinal değer</span><p>{formatScalar(value)}</p></div>;
}
function ScalarInput({ field, label, multiline, onFocus }: {
  field: ReviewField; label: string; multiline?: boolean; onFocus?: () => void;
}) {
  const c = useCtx();
  const st = fieldState(c, field);
  if (!st) return null;
  const common = { "aria-label": label, "aria-invalid": st.error ? true : undefined, disabled: c.locked, onFocus };
  if (typeof field.value === "boolean") {
    return <Select disabled={c.locked} value={String(st.raw)} onValueChange={value => c.setDraft(field, value === "true")}>
      <SelectTrigger {...common} className="w-full bg-paper text-sm"><SelectValue>{st.raw === true || st.raw === "true" ? "Doğru" : "Yanlış"}</SelectValue></SelectTrigger>
      <SelectContent><SelectItem value="true">Doğru</SelectItem><SelectItem value="false">Yanlış</SelectItem></SelectContent>
    </Select>;
  }
  const text = String(st.raw);
  if (multiline) {
    return <Textarea {...common} placeholder={field.kind === "description" ? "Anlamı henüz açıklanmadı. Kaynak görselde gördüğünüz bilgiyi yazın…" : undefined} className="w-full border border-solid border-line rounded-sm bg-paper text-ink [&:focus]:border-accent [&:focus]:[box-shadow:0_0_0_3px_var(--accent-soft)] [&:focus]:[outline:none] [&[aria-invalid='true']]:border-danger [&[aria-invalid='true']]:bg-danger-soft [&:disabled]:opacity-[.6] font-normal text-base leading-[1.65] font-serif resize-y p-2" value={text} rows={Math.min(16, Math.max(3, text.split("\n").length + 1))}
      onChange={(e) => c.setDraft(field, e.target.value)} />;
  }
  return <Input {...common} className="w-full border border-solid border-line rounded-sm bg-paper text-ink text-sm [&:focus]:border-accent [&:focus]:[box-shadow:0_0_0_3px_var(--accent-soft)] [&:focus]:[outline:none] [&[aria-invalid='true']]:border-danger [&[aria-invalid='true']]:bg-danger-soft [&:disabled]:opacity-[.6] p-2" value={text} inputMode={typeof field.value === "number" ? "decimal" : undefined}
    onChange={(e) => c.setDraft(field, e.target.value)} />;
}

function TextBlock({ node, field, compact }: { node: Node; field: ReviewField | null; compact?: boolean }) {
  const c = useCtx();
  const st = fieldState(c, field);
  const [editing, setEditing] = useState(false);
  const text = st ? (typeof st.raw === "boolean" ? formatScalar(st.raw) : st.raw) : node.text ?? "";
  const selected = c.selection?.nodeId === node.id;
  const target: Selection = { nodeId: node.id, fieldId: field?.field_id };
  return <article id={`rw-node-${node.id}`} className={cn(`relative pt-3 pr-4 pb-2 pl-5 bg-paper border border-solid border-line2 rounded-xs motion-safe:transition-colors motion-safe:duration-150 [&::before]:content-[''] [&::before]:absolute [&::before]:left-0 [&::before]:top-2 [&::before]:bottom-2 [&::before]:w-[3px] [&::before]:rounded-xs [&::before]:bg-transparent [&:hover]:border-line${compact ? " pt-2 pb-1 px-3 my-1 mx-0" : ""}${selected ? " border-accent-line [box-shadow:0_0_0_3px_var(--accent-soft)] [&::before]:bg-accent" : ""}${st?.changed ? " [&::before]:bg-warn" : ""}`)}
    onClick={() => c.select(target)}>
    <div className="flex flex-wrap mb-2 [&:empty]:hidden gap-1">
      {st ? <AccessChip editable={st.editable} reason={st.reason} /> : <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-sheet text-faint py-1 px-2">Salt okunur · bu içerik için düzenleme alanı yok</span>}
      {st?.changed && <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-warn-soft text-warn py-1 px-2">Taslakta değişti</span>}
    </div>
    {editing && st?.editable && field ? <ScalarInput field={field} label={field.label} multiline onFocus={() => c.select(target)} />
      : <p className={documentProse}>{text ? <Highlight text={text} query={c.query} /> : <span className="text-faint italic">(boş)</span>}</p>}
    {st?.changed && field && <Original value={field.value} />}
    {st?.error && <p className="mt-1 mb-0 text-danger text-xs mx-0" role="alert">{st.error}</p>}
    <div className="flex flex-wrap gap-y-1 gap-x-4 mt-2">
      <Button variant="ghost" type="button" className={sourceAction} onClick={(e) => { e.stopPropagation(); c.select(target, true); }}>Kaynakta göster</Button>
      {st?.editable && field && <Button variant="ghost" type="button" className={sourceAction} aria-pressed={editing} disabled={c.locked}
        onClick={(e) => { e.stopPropagation(); c.select(target); setEditing(!editing); }}>{editing ? "Düzenlemeyi kapat" : "Düzenle"}</Button>}
      {st?.changed && field && <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal bg-transparent border-0 text-xs font-semibold [text-decoration:underline] [text-underline-offset:3px] [&:disabled]:opacity-[.45] text-warn py-1 px-0" disabled={c.locked}
        onClick={(e) => { e.stopPropagation(); c.revert(field); }}>Geri al</Button>}
    </div>
  </article>;
}
function ListView({ node }: { node: Node }) {
  const c = useCtx();
  const items = (node.children ?? []).map((id) => c.nodes.get(id)).filter((item): item is Node => !!item);
  const textField = (n: Node) => c.fieldsByNode.get(n.id)?.find((f) => f.kind === "text") ?? null;
  if (!items.length) return <TextBlock node={node} field={textField(node)} />;
  const Tag: "ol" | "ul" = node.ordered ? "ol" : "ul";
  return <Tag className="pl-5 grid gap-1 m-0">{items.map((item) => <li key={item.id}>
    {item.kind === "list" ? <ListView node={item} /> : <TextBlock node={item} field={textField(item)} compact />}
  </li>)}</Tag>;
}

function TextPanel({ blocks }: { blocks: ReadBlock[] }) {
  const c = useCtx();
  const needle = norm(c.query.trim());
  const textField = (n: Node) => c.fieldsByNode.get(n.id)?.find((f) => f.kind === "text") ?? null;
  const nodeText = (n: Node): string => {
    const field = textField(n);
    const own = field ? (typeof (c.drafts[field.field_id] ?? toRaw(field.value)) === "boolean" ? "" : String(c.drafts[field.field_id] ?? toRaw(field.value))) : n.text ?? "";
    return own + (n.kind === "list" ? " " + (n.children ?? []).map((id) => { const child = c.nodes.get(id); return child ? nodeText(child) : ""; }).join(" ") : "");
  };
  if (needle) {
    const hits = blocks.filter(({ node }) => node.kind !== "section" && ["text_block", "list"].includes(node.kind) && norm(nodeText(node)).includes(needle));
    if (!hits.length) return <Empty title="Eşleşen metin yok" detail="Aramanızı değiştirin; tablolar ve görseller kendi bölümlerinde aranır." />;
    return <div className="flex flex-col gap-2">{hits.map(({ node, trail }) => <div key={node.id} className="rounded-xs bg-warn-soft px-1 text-inherit">
      {trail.length > 0 && <p className="mt-0 mb-1 text-2xs text-faint mx-0">{trail.join(" › ")}</p>}
      {node.kind === "list" ? <ListView node={node} /> : <TextBlock node={node} field={textField(node)} />}
    </div>)}</div>;
  }
  const visible = blocks.filter(({ node }) => node.kind !== "section" || node.heading || node.title);
  if (!visible.length) return <Empty title="Metin bulunamadı" detail="Bu içerikte okunabilir metin içeriği yok." />;
  return <div className="flex flex-col gap-2">{visible.map(({ node, depth }) => {
    if (node.kind === "section") {
      const Heading = (`h${Math.min(5, Math.max(3, (node.level ?? depth) + 2))}`) as "h3" | "h4" | "h5";
      const field = textField(node);
      const st = fieldState(c, field);
      return <section key={node.id} id={`rw-node-${node.id}`}>
        <Heading className="mt-5 mb-1 font-semibold text-lg leading-[1.25] font-serif text-ink pb-1 border-b border-solid border-b-line [h4&]:text-md [h4&]:border-b-0 [h5&]:text-base [h5&]:border-b-0 mx-0">{field ? String(c.drafts[field.field_id] ?? field.value) : node.heading || node.title}</Heading>
        {field && st?.editable && <details><summary>Başlığı düzenle</summary>
          <ScalarInput field={field} label="Bölüm başlığı" onFocus={() => c.select({ nodeId: node.id, fieldId: field.field_id })} />
          {st.changed && <><Original value={field.value} /><Button variant="ghost" type="button" className={sourceAction} onClick={() => c.revert(field)}>Geri al</Button></>}
        </details>}
        <Button variant="ghost" type="button" className={sourceAction} onClick={() => c.select({ nodeId: node.id, fieldId: field?.field_id }, true)}>Başlığı kaynakta göster</Button>
      </section>;
    }
    if (node.kind === "list") return <ListView key={node.id} node={node} />;
    if (node.kind === "table") {
      const edits = (c.fieldsByNode.get(node.id) ?? []).filter((f) => c.drafts[f.field_id] !== undefined).length;
      return <div className="flex items-center justify-between border border-solid border-line rounded-xs bg-sheet [&_strong]:block [&_strong]:font-semibold [&_strong]:text-base [&_strong]:font-sans [&_small]:text-faint [&_small]:text-2xs [&_>_div]:min-w-0 [&_>_div]:wrap-anywhere gap-3 py-3 px-4" key={node.id}><div><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-accent">Tablo</span><strong>{nodeTitle(node, "Adsız tablo")}</strong>
        <small>{node.rows?.length ?? 0} satır{edits ? ` · ${edits} hücre taslakta` : ""}</small></div>
        <Button variant="ghost" type="button" className={reviewAction} onClick={() => c.openSection("tables", node.id)}>Tabloyu aç</Button></div>;
    }
    if (node.kind === "asset" || node.kind === "chart") {
      return <div className="flex items-center justify-between border border-solid border-line rounded-xs bg-sheet [&_strong]:block [&_strong]:font-semibold [&_strong]:text-base [&_strong]:font-sans [&_small]:text-faint [&_small]:text-2xs [&_>_div]:min-w-0 [&_>_div]:wrap-anywhere gap-3 py-3 px-4" key={node.id}><div><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-accent">{node.kind === "chart" ? "Grafik" : "Görsel"}</span>
        <strong>{node.description?.trim() ? node.caption || node.description : "Açıklama yok — ekle"}</strong></div>
        <Button variant="ghost" type="button" className={reviewAction} onClick={() => c.openSection("visuals", node.id)}>Görseli aç</Button></div>;
    }
    return <TextBlock key={node.id} node={node} field={textField(node)} />;
  })}</div>;
}

function CellView({ slot, row, col }: { slot: GridSlot; row: number; col: number }) {
  const c = useCtx();
  const st = fieldState(c, slot.field);
  const q = norm(c.query.trim());
  const text = slotText(slot, c.drafts);
  const hit = !!q && norm(text).includes(q);
  const active = !!slot.field && c.selection?.fieldId === slot.field.field_id;
  const tableId = slot.field?.node_id ?? "";
  const label = `Satır ${row + 1}, sütun ${col + 1}`;
  const target: Selection | null = slot.field ? { nodeId: tableId, fieldId: slot.field.field_id } : null;
  return <div className={cn(`relative min-h-8 grid py-1 px-2 gap-1${hit ? " bg-warn-soft" : ""}${active ? " [box-shadow:inset_0_0_0_2px_var(--accent)]" : ""}${st?.changed ? " bg-warn-soft [box-shadow:inset_0_-2px_0_var(--warn)]" : ""}${st?.error ? " bg-danger-soft" : ""}`)}>
    {st?.editable && slot.field ? <ScalarInput field={slot.field} label={label} multiline={typeof slot.field.value === "string" && slot.field.value.includes("\n")}
      onFocus={() => target && c.select(target)} />
      : <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal bg-transparent border-0 text-left text-xs leading-[1.45] whitespace-pre-wrap wrap-anywhere w-full py-1 px-0" aria-label={`${label}: ${text || "boş"}`} onClick={() => target && c.select(target)}>
        {text ? <Highlight text={text} query={c.query} /> : <span className="text-faint italic">·</span>}
      </Button>}
    {slot.cell.formula && <small className="font-normal text-2xs leading-[1.4] font-mono text-faint wrap-anywhere">ƒ {slot.cell.formula}</small>}
    {st && !st.editable && <small className="font-normal text-2xs leading-[1.4] font-mono text-faint wrap-anywhere">Salt okunur</small>}
    {st?.changed && slot.field && <small className="font-normal text-2xs leading-[1.4] font-mono wrap-anywhere text-warn line-through">Orijinal: {formatScalar(slot.field.value)}</small>}
    {st?.error && <small className="font-normal font-mono wrap-anywhere mt-1 mb-0 text-danger text-xs mx-0" role="alert">{st.error}</small>}
  </div>;
}

function TablesPanel({ blocks, tableId, setTableId, grids }: {
  blocks: ReadBlock[]; tableId: string; setTableId: (id: string) => void; grids: Map<string, Grid>;
}) {
  const c = useCtx();
  const [headerOverride, setHeaderOverride] = useState<Record<string, boolean>>({});
  const q = norm(c.query.trim());
  const tables = blocks.filter((b) => b.node.kind === "table");
  const hasHit = (id: string) => !!q && !!grids.get(id)?.rows.flat().some((slot) => norm(slotText(slot, c.drafts)).includes(q));
  const shown = q ? tables.filter((t) => hasHit(t.node.id)) : tables;
  if (!tables.length) return <Empty title="Tablo yok" detail="Bu içerikte tablo bulunmuyor." />;
  if (!shown.length) return <Empty title="Eşleşen tablo yok" detail="Aramanız hiçbir tablo hücresinde bulunamadı." />;
  const current = shown.find((t) => t.node.id === tableId) ?? shown[0];
  const grid = grids.get(current.node.id) ?? { rows: [], loose: [] };
  const header = headerOverride[current.node.id] ?? defaultHeader(grid);
  const columns = Math.max(0, ...grid.rows.map((row) => row.length));
  const selectedField = c.selection?.fieldId ? (c.fieldsByNode.get(current.node.id) ?? []).find((f) => f.field_id === c.selection?.fieldId) : undefined;
  const selectedState = fieldState(c, selectedField ?? null);
  return <div className="grid gap-3">
    <div className="flex overflow-x-auto pb-1 gap-2" role="group" aria-label="Tablolar">
      {shown.map((t, index) => {
        const edits = (c.fieldsByNode.get(t.node.id) ?? []).filter((f) => c.drafts[f.field_id] !== undefined).length;
        return <Button variant="ghost" type="button" key={t.node.id} className="h-auto min-h-7 whitespace-normal flex-none max-w-60 text-left grid border border-solid border-line rounded-sm bg-paper [&_strong]:font-semibold [&_strong]:text-sm [&_strong]:leading-[1.3] [&_strong]:font-sans [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_small]:text-faint [&_small]:text-2xs [&[aria-pressed='true']]:border-accent [&[aria-pressed='true']]:[box-shadow:inset_3px_0_0_var(--accent)] [&[aria-pressed='true']]:bg-accent-soft gap-1 py-2 px-3" aria-pressed={t.node.id === current.node.id} onClick={() => setTableId(t.node.id)}>
          <span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-accent">Tablo {index + 1}</span><strong>{nodeTitle(t.node, "Adsız tablo")}</strong>
          <small>{t.node.rows?.length ?? 0} × {Math.max(0, ...(t.node.rows ?? []).map((r) => r.length))}{edits ? ` · ${edits} değişiklik` : ""}</small>
        </Button>;
      })}
    </div>
    <section className="bg-paper border border-solid border-line rounded-sm grid min-w-0 [&_>_header]:flex [&_>_header]:flex-wrap [&_>_header]:items-end [&_>_header]:justify-between [&_>_header]:gap-y-2 [&_>_header]:gap-x-4 [&_h3]:font-semibold [&_h3]:text-lg [&_h3]:leading-[1.25] [&_h3]:font-sans gap-3 p-4 [&_h3]:m-0" id={`rw-node-${current.node.id}`}>
      <header>
        <div>{current.trail.length > 0 && <p className="mt-0 mb-1 text-2xs text-faint mx-0">{current.trail.join(" › ")}</p>}
          <h3>{nodeTitle(current.node, "Adsız tablo")}</h3></div>
        <label className="inline-flex items-start text-xs text-ink2 [&_input]:mt-1 [&_input]:accent-accent gap-2"><input type="checkbox" checked={header} onChange={(e) => setHeaderOverride({ ...headerOverride, [current.node.id]: e.target.checked })} />
          İlk satır sütun başlığı</label>
      </header>
      <div className="max-w-full max-h-[70vh] overflow-auto border border-solid border-line rounded-xs" role="region" aria-label="Tablo içeriği" tabIndex={0}>
        <Table containerClassName="overflow-visible" className="[&_td]:whitespace-normal [&_mark]:bg-warn-soft [&_mark]:text-inherit [&_mark]:rounded-xs [border-collapse:separate] [border-spacing:0] w-[max-content] min-w-full text-xs [&_th]:border-r [&_th]:border-solid [&_th]:border-r-line2 [&_th]:border-b [&_th]:border-b-line2 [&_th]:align-[top] [&_th]:bg-paper [&_th]:min-w-[110px] [&_td]:border-r [&_td]:border-solid [&_td]:border-r-line2 [&_td]:border-b [&_td]:border-b-line2 [&_td]:align-[top] [&_td]:bg-paper [&_td]:min-w-[110px] [&_thead_th]:sticky [&_thead_th]:top-0 [&_thead_th]:z-[2] [&_thead_th]:bg-sheet [&_tbody_tr:nth-child(even)_td]:bg-paper [&_mark]:py-0 [&_mark]:px-1 [&_th]:p-0 [&_td]:p-0">
          <TableHeader>
            <TableRow><TableHead className="sticky left-0 z-[3]! min-w-[34px]! w-[34px]! text-center font-semibold text-2xs font-mono text-faint bg-sheet" scope="col"><span className="absolute w-[1px] h-[1px] overflow-hidden [clip:rect(0_0_0_0)] whitespace-nowrap">Satır</span></TableHead>
              {Array.from({ length: columns }, (_, i) => <TableHead key={i} scope="col" className="font-semibold text-2xs font-mono tracking-[.06em] uppercase text-faint text-left py-1 px-2">Sütun {i + 1}</TableHead>)}</TableRow>
            {header && grid.rows[0] && <TableRow><TableHead className="sticky left-0 z-[1] min-w-[34px]! w-[34px]! text-center font-semibold text-2xs font-mono text-faint bg-sheet" scope="row">1</TableHead>
              {grid.rows[0].map((slot, i) => slot.covered ? null : <TableHead key={i} scope="col" className="bg-sheet font-semibold top-6!" rowSpan={slot.cell.row_span} colSpan={slot.cell.col_span}>
                <CellView slot={slot} row={0} col={i} /></TableHead>)}</TableRow>}
          </TableHeader>
          <TableBody>
            {grid.rows.map((row, r) => header && r === 0 ? null : <TableRow key={r}>
              <TableHead className="sticky left-0 z-[1] min-w-[34px]! w-[34px]! text-center font-semibold text-2xs font-mono text-faint bg-sheet" scope="row">{r + 1}</TableHead>
              {row.map((slot, i) => slot.covered ? null : <TableCell key={i} rowSpan={slot.cell.row_span} colSpan={slot.cell.col_span}><CellView slot={slot} row={r} col={i} /></TableCell>)}
            </TableRow>)}
          </TableBody>
        </Table>
      </div>
      <p className="text-faint text-xs leading-[1.55] m-0" aria-live="polite">{selectedField && selectedState ? <>
        <strong>{selectedField.label}</strong> · <AccessChip editable={selectedState.editable} reason={selectedState.reason} /></> :
        "Bir hücre seçtiğinizde kaynak konumu solda gösterilir. Birleşik hücreler tek hücre olarak görünür; formüllü hücreler düzenlenemez."}</p>
      {grid.loose.length > 0 && <details className="[&_summary]:cursor-pointer [&_summary]:text-xs [&_summary]:font-semibold">
        <summary>Hücre listesi · tablo ızgarasıyla eşleştirilemedi ({grid.loose.length})</summary>
        <p className="text-faint text-xs leading-[1.55] m-0">Bu tablodaki hücreler ızgaraya güvenle yerleştirilemedi; ızgara salt okunur gösteriliyor. Değerleri aşağıdan düzenleyebilirsiniz.</p>
        <ul className="[list-style:none] mt-2 mb-0 grid [&_li]:border [&_li]:border-solid [&_li]:border-line2 [&_li]:rounded-sm [&_label]:grid [&_label]:text-xs [&_label]:font-semibold mx-0 gap-2 [&_li]:py-2 [&_li]:px-3 [&_label]:gap-1 p-0">{grid.loose.map((field) => <LooseField key={field.field_id} field={field} />)}</ul>
      </details>}
    </section>
  </div>;
}
function LooseField({ field }: { field: ReviewField }) {
  const c = useCtx();
  const st = fieldState(c, field);
  if (!st) return null;
  return <li className={st.changed ? "" : ""}>
    <label><span>{field.label}</span>
      {st.editable ? <ScalarInput field={field} label={field.label} onFocus={() => c.select({ nodeId: field.node_id, fieldId: field.field_id })} />
        : <span className={documentProse}>{formatScalar(field.value)} <AccessChip editable={false} reason={st.reason} /></span>}
    </label>
    {st.changed && <Original value={field.value} />}
    {st.error && <p className="mt-1 mb-0 text-danger text-xs mx-0" role="alert">{st.error}</p>}
  </li>;
}

function ArtifactImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return failed ? <div className="text-center border border-dashed border-line rounded-sm text-faint text-xs bg-paper py-6 px-3">Görsel dosyası yüklenemedi.</div>
    : <img className="w-full max-h-85 object-contain border border-solid border-line bg-paper" src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />;
}
function VisualsPanel({ blocks, snapshot }: { blocks: ReadBlock[]; snapshot: Snapshot }) {
  const c = useCtx();
  const developerMode = useDeveloperMode();
  const q = norm(c.query.trim());
  const coverage = snapshot.metadata.structural_parse?.coverage?.item_counts?.picture ?? 0;
  const undetected = (snapshot.metadata.structural_parse?.issues ?? []).filter((issue) => issue.code === "unextracted_picture").length;
  const assets = blocks.filter((b) => b.node.kind === "asset" || b.node.kind === "chart").filter(({ node }) => {
    if (!q) return true;
    const field = c.fieldsByNode.get(node.id)?.find((f) => f.kind === "description");
    return norm(`${node.caption ?? ""} ${field ? String(c.drafts[field.field_id] ?? toRaw(field.value)) : node.description ?? ""}`).includes(q);
  });
  return <div className="grid gap-3">
    <p className="text-xs leading-[1.55] text-ink2 bg-paper border border-solid border-line2 rounded-sm py-2 px-3 m-0">Dosya türü ve boyutu gibi bilgiler yalnızca dosyayı tanımlar. Bir görselin anlamı, açıklama yazılıp kaynakla kontrol edilene kadar bilinmiyor sayılır.</p>
    {undetected > 0 && <div className="border-l-[4px] border-solid border-l-warn bg-warn-soft rounded-xs text-xs py-3 px-4">{undetected} görsel kaynakta tespit edildi ancak dosyası çıkarılamadığı için burada önizlenemiyor{coverage ? ` (toplam ${coverage} görsel)` : ""}.</div>}
    {!assets.length ? <Empty title={q ? "Eşleşen görsel yok" : "Görsel yok"} detail={q ? "Aramanızı değiştirin." : "Bu içerikte görsel veya grafik kaydı bulunmuyor."} />
      : <div className="grid gap-3">{assets.map(({ node }) => {
        const artifact = snapshot.artifacts.find((item) => item.id === node.artifact_id);
        const field = c.fieldsByNode.get(node.id)?.find((f) => f.kind === "description") ?? null;
        const st = fieldState(c, field);
        const description = field ? (typeof (c.drafts[field.field_id] ?? toRaw(field.value)) === "boolean" ? "" : String(c.drafts[field.field_id] ?? toRaw(field.value))) : node.description ?? "";
        const uncertainties = storedVisualUncertainties(snapshot, node.id);
        const uncertaintyText = field ? c.uncertaintyDrafts[field.field_id] ?? uncertainties.join("\n") : uncertainties.join("\n");
        const notesChanged = uncertaintyText !== uncertainties.join("\n");
        const target: Selection = { nodeId: node.id, fieldId: field?.field_id };
        return <article key={node.id} id={`rw-node-${node.id}`} className={cn(`relative grid grid-cols-[minmax(150px,_40%)_minmax(0,_1fr)] bg-paper border border-solid border-line2 rounded-xs [&::before]:content-[''] [&::before]:absolute [&::before]:left-0 [&::before]:top-2 [&::before]:bottom-2 [&::before]:w-[3px] [&::before]:bg-transparent [&::before]:rounded-xs max-[640px]:grid-cols-[minmax(0,_1fr)] gap-4 p-3${c.selection?.nodeId === node.id ? " [&::before]:bg-accent border-accent-line [box-shadow:0_0_0_3px_var(--accent-soft)]" : ""}${st?.changed ? " [&::before]:bg-warn" : ""}`)}
          onClick={() => c.select(target)}>
          <div className="min-w-0">
            {artifact && artifact.mime_type.startsWith("image/") ?
              <ArtifactImage src={`${API}/v1/knowledge/revisions/${encodeURIComponent(snapshot.knowledge_revision.id)}/artifacts/${encodeURIComponent(artifact.id)}`}
                alt={node.caption || node.description || "Belgeden çıkarılan görsel"} />
              : <div className="text-center border border-dashed border-line rounded-sm text-faint text-xs bg-paper py-6 px-3">{artifact ? "Bu dosya türü önizlenemiyor." : "Bu görsel için dosya çıkarılamadı."}</div>}
          </div>
          <div className="grid [align-content:start] min-w-0 [&_h3]:font-semibold [&_h3]:text-md [&_h3]:leading-[1.3] [&_h3]:font-sans gap-1 [&_h3]:m-0">
            <span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-accent">{node.kind === "chart" ? "Grafik" : "Görsel"}</span>
            <h3>{description.trim() ? node.caption || description.split(".")[0] : "Açıklama yok — ekle"}</h3>
            {developerMode && artifact && <p className="text-faint text-2xs my-1 mx-0">Dosya bilgisi: {artifact.mime_type} · {artifact.byte_size.toLocaleString("tr-TR")} bayt. Bu bilgi görselin anlamını doğrulamaz.</p>}
            <div className="flex flex-wrap mb-2 [&:empty]:hidden gap-1">{st ? <AccessChip editable={st.editable} reason={st.reason} /> : <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-sheet text-faint py-1 px-2">Salt okunur · açıklama alanı yok</span>}
              {(st?.changed || notesChanged) && <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-warn-soft text-warn py-1 px-2">Taslakta değişti</span>}</div>
            {st?.editable && field ? <ScalarInput field={field} label={`${field.label} (görsel açıklaması)`} multiline onFocus={() => c.select(target)} />
              : <p className={documentProse}>{description ? <Highlight text={description} query={c.query} /> : <span className="text-faint italic">Anlamı bilinmiyor · açıklama yok</span>}</p>}
            {st?.changed && field && <Original value={field.value} />}
            {st?.error && <p className="mt-1 mb-0 text-danger text-xs mx-0" role="alert">{st.error}</p>}
            {uncertainties.length > 0 && <div className="text-xs leading-[1.55] text-warn m-0"><strong>Görselde belirsiz kalan bilgiler</strong><ul>{uncertainties.map((item, i) => <li key={i}>{item}</li>)}</ul></div>}
            {st?.editable && field && <details><summary>Belirsizlik notlarını düzenle</summary>
              <label><span className="text-faint text-xs leading-[1.55] m-0">Her satır bir not (en fazla 20). Yalnız kaynakta doğruladığınız belirsizlikleri kaldırın.</span>
                <Textarea className="font-normal text-base leading-[1.65] font-serif resize-y" aria-label="Görsel belirsizlik notları" rows={3} value={uncertaintyText} disabled={c.locked}
                  onChange={(e) => c.setUncertaintyDraft(field, e.target.value)} onFocus={() => c.select(target)} /></label>
            </details>}
            <div className="flex flex-wrap gap-y-1 gap-x-4 mt-2">
              <Button variant="ghost" type="button" className={sourceAction} onClick={(e) => { e.stopPropagation(); c.select(target, true); }}>Kaynakta göster</Button>
              {(st?.changed || notesChanged) && field && <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal bg-transparent border-0 text-xs font-semibold [text-decoration:underline] [text-underline-offset:3px] [&:disabled]:opacity-[.45] text-warn py-1 px-0" disabled={c.locked} onClick={(e) => { e.stopPropagation(); c.revert(field); }}>Geri al</Button>}
            </div>
            {developerMode && artifact && artifact.mime_type.startsWith("image/") && field && typeof field.value !== "boolean" &&
              <LocalVisualProposal revisionId={snapshot.knowledge_revision.id} snapshotSha256={c.snapshotSha256} nodeId={node.id} mode={c.mode}
                canAdopt={!!st?.editable} locked={c.locked} onAdopt={(text, proposal) => c.adoptProposal(field, text, proposal)} />}
          </div>
        </article>;
      })}</div>}
  </div>;
}

function storedVisualUncertainties(snapshot: Snapshot, nodeId: string): string[] {
  const reviews = (snapshot.metadata as { visual_review?: Record<string, { uncertainties?: unknown }> }).visual_review;
  const list = reviews && typeof reviews === "object" ? reviews[nodeId]?.uncertainties : null;
  return Array.isArray(list) ? list.filter((item): item is string => typeof item === "string") : [];
}
function computeGaps(ws: Workspace, fieldsByNode: Map<string, ReviewField[]>, blocks: ReadBlock[]): Gap[] {
  const gaps = new Map<string, Gap>();
  const add = (key: string, title: string, detail: string, nodeId?: string) => {
    const existing = gaps.get(key);
    if (existing) existing.count += 1; else gaps.set(key, { key, title, detail, nodeId, count: 1 });
  };
  ws.warnings.forEach((warning, i) => add(`w-${i}`, "Uyarı", warning));
  const parse = ws.snapshot.metadata.structural_parse;
  (parse?.issues ?? []).forEach((issue, i) => {
    const known = issue.code ? ISSUE_TEXT[issue.code] : undefined;
    add(`i-${issue.code ?? i}-${issue.reason ?? ""}`, known?.[0] ?? issue.reason ?? issue.code ?? "Çıkarım notu",
      known?.[1] ?? issue.impact ?? issue.reason ?? "");
  });
  (parse?.coverage?.skipped_areas ?? []).forEach((area) => add(`s-${area}`, "Atlanan alan", `“${area}” alanı işlenmedi.`));
  for (const { node } of blocks) {
    if (node.kind !== "asset" && node.kind !== "chart") continue;
    const field = fieldsByNode.get(node.id)?.find((f) => f.kind === "description");
    const description = field ? field.value : node.description;
    for (const [i, uncertainty] of storedVisualUncertainties(ws.snapshot, node.id).entries()) {
      add(`vu-${node.id}-${i}`, "Görselde belirsiz bilgi", uncertainty, node.id);
    }
    if (description == null || description === "") {
      add(`d-${node.id}`, node.kind === "chart" ? "Grafiğin anlamı bilinmiyor" : "Görselin anlamı bilinmiyor",
        `${node.caption || "Başlıksız öğe"} için açıklama yok; kaynağa bakıp açıklama ekleyin.`, node.id);
    }
  }
  return Array.from(gaps.values());
}
function GapsPanel({ gaps }: { gaps: Gap[] }) {
  const developerMode = useDeveloperMode();
  const c = useCtx();
  return <div className="grid gap-3">
    <p className="text-xs leading-[1.55] text-ink2 bg-paper border border-solid border-line2 rounded-sm py-2 px-3 m-0">Bu liste kayıtlı eksikleri gösterir. Listenin boş olması, kaynaktaki bütün anlamın doğru çıkarıldığı anlamına gelmez.</p>
    {!gaps.length ? <Empty title="Kayıtlı eksik yok" detail="Sistem bu içerik için eksik kaydı üretmedi; yine de içeriği kaynakla karşılaştırın." /> :
      <ul className="[list-style:none] grid gap-2 m-0 p-0">{gaps.map((gap) => <li key={gap.key} className="flex justify-between items-start bg-paper border border-solid border-line2 border-l-[3px] border-l-warn rounded-xs [&_strong]:text-sm [&_p]:mt-1 [&_p]:mb-0 [&_p]:text-ink2 [&_p]:text-xs gap-3 py-3 px-4 [&_p]:mx-0">
        <div><strong>{developerMode || gap.nodeId ? gap.title : "İnceleme gerekiyor"}{gap.count > 1 ? ` · ${gap.count} kayıt` : ""}</strong>{gap.detail && <p>{developerMode || gap.nodeId ? gap.detail : "Bu bölümdeki bilgileri özgün dosyayla karşılaştırın."}</p>}</div>
        {gap.nodeId && <Button variant="ghost" type="button" className={reviewAction} onClick={() => c.openSection("visuals", gap.nodeId)}>Öğeye git</Button>}
      </li>)}</ul>}
  </div>;
}

function HistoryPanel({ ws, numbers, displayed, locked, onView }: {
  ws: Workspace; numbers: Map<string, number>; displayed: string; locked: boolean; onView: (id: string) => void;
}) {
  const entries = [...ws.history].sort((a, b) => (numbers.get(b.revision_id) ?? 0) - (numbers.get(a.revision_id) ?? 0));
  return <div className="grid gap-3">
    <p className="text-xs leading-[1.55] text-ink2 bg-paper border border-solid border-line2 rounded-sm py-2 px-3 m-0"><b>Düzenleme geçmişi</b> bu belgenin içeriğinde yapılan incelemeleri gösterir. Dosya sürümleri yüklenen dosyanın geçmişini gösterir; bir düzenleme kaydetmek kaynak dosyayı değiştirmez.
      Eski düzenlemeler yalnızca görüntülenir; geri yükleme veya onaylama burada yoktur.</p>
    <ol className="[list-style:none] grid gap-2 m-0 p-0">{entries.map((entry) => {
      const isLatest = entry.revision_id === ws.latest_revision_id, shown = entry.revision_id === displayed;
      return <li key={entry.revision_id} className={cn(`relative pr-4 pl-5 bg-paper border border-solid border-line2 rounded-xs [&::before]:content-[''] [&::before]:absolute [&::before]:left-[9px] [&::before]:top-[18px] [&::before]:w-[7px] [&::before]:h-[7px] [&::before]:rounded-pill [&::before]:bg-line py-3${shown ? " border-accent-line [&::before]:bg-accent" : ""}`)}>
        <div className="flex flex-wrap items-center gap-2">
          <strong>Düzenleme {numbers.get(entry.revision_id)}</strong>
          {isLatest && <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-accent-soft text-accent py-1 px-2">Güncel</span>}
          {entry.revision_id === ws.approved_revision_id && <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-ok-soft text-ok py-1 px-2">Onaylı sürüm</span>}
          {shown && <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-warn-soft text-warn py-1 px-2">Görüntüleniyor</span>}
        </div>
        <p className="text-faint text-2xs my-1 mx-0">{entry.kind === "manual_review" ? "Manuel inceleme" : "İlk çıkarım"} · {dateText(entry.created_at)}</p>
        <p className="text-faint text-2xs my-1 mx-0">İnceleyen: {entry.reviewer_id || "kayıtlı değil"}</p>
        {entry.reason && <p className={documentProse}>{entry.reason}</p>}
        {!shown && <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal inline-flex items-center justify-center border border-solid border-line rounded-sm bg-paper text-ink text-xs font-semibold no-underline cursor-pointer motion-safe:transition-colors motion-safe:duration-150 [&:hover:not(:disabled)]:border-accent [&:hover:not(:disabled)]:bg-accent-soft [&:disabled]:opacity-[.45] [&:disabled]:cursor-default mt-2 gap-1 py-2 px-3" disabled={locked} onClick={() => onView(entry.revision_id)}>
          {isLatest ? "Güncel içeriği göster" : "Bu içeriği görüntüle"}</Button>}
      </li>;
    })}</ol>
  </div>;
}

function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="border border-dashed border-line rounded-lg bg-paper [&_strong]:font-semibold [&_strong]:text-md [&_strong]:font-sans [&_p]:mt-1 [&_p]:mb-0 [&_p]:text-faint [&_p]:text-xs [&_p]:max-w-[62ch] py-8 px-6 [&_p]:mx-0"><strong>{title}</strong><p>{detail}</p></div>;
}

function SourcePanel({ ws, evidences, activeId, setActiveId, page, setPage, hasSelection, panelRef }: {
  ws: Workspace; evidences: Evidence[]; activeId: string | null; setActiveId: (id: string) => void;
  page: number; setPage: (n: number) => void; hasSelection: boolean; panelRef: React.RefObject<HTMLElement | null>;
}) {
  const developerMode = useDeveloperMode();
  const [failed, setFailed] = useState<string | null>(null);
  const pages = useMemo(() => [...ws.source.pages].sort((a, b) => a.page_number - b.page_number), [ws.source.pages]);
  const active = evidences.find((e) => e.id === activeId) ?? evidences[0];
  const index = Math.max(0, pages.findIndex((p) => p.page_number === page));
  const current = pages[index];
  const boxes = evidences.filter((e): e is Evidence & { locator: Extract<Locator, { kind: "pdf_page" }> } =>
    e.locator.kind === "pdf_page" && !!e.locator.bbox && e.locator.page_number === current?.page_number);
  return <aside className="sticky top-[140px] max-h-[calc(100vh_-_156px)] overflow-auto bg-sheet border border-solid border-line rounded-xs shadow-none flex flex-col max-[1000px]:static max-[1000px]:max-h-[none] gap-3 p-4" ref={panelRef} aria-label="Kaynak belge">
    <header className="grid [justify-items:start] [&_h2]:mt-0 [&_h2]:mb-1 [&_h2]:font-semibold [&_h2]:text-md [&_h2]:leading-[1.3] [&_h2]:font-sans [&_h2]:wrap-anywhere gap-1 [&_h2]:mx-0">
      <span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-accent">Kaynak</span>
      <h2>{ws.source.filename}</h2>
      <a className="inline-flex items-center justify-center border border-solid border-line rounded-sm bg-paper text-ink text-xs font-semibold no-underline cursor-pointer motion-safe:transition-colors motion-safe:duration-150 [&:hover:not(:disabled)]:border-accent [&:hover:not(:disabled)]:bg-accent-soft [&:disabled]:opacity-[.45] [&:disabled]:cursor-default gap-1 py-2 px-3" href={absolute(ws.source.download_url)} download>Orijinali indir</a>
    </header>
    {evidences.length > 0 && <div className="flex flex-wrap [&_button]:border [&_button]:border-solid [&_button]:border-line [&_button]:bg-paper [&_button]:rounded-pill [&_button]:text-2xs [&_button[aria-pressed='true']]:bg-accent [&_button[aria-pressed='true']]:border-accent [&_button[aria-pressed='true']]:text-on-accent gap-1 [&_button]:py-1 [&_button]:px-3" role="group" aria-label="Seçili içeriğin kaynak konumları">
      {evidences.map((e) => <Button variant="ghost" type="button" key={e.id} aria-pressed={e.id === active?.id} onClick={() => setActiveId(e.id)}>{locatorLabel(e.locator)}</Button>)}
    </div>}
    {!hasSelection && <p className="text-faint text-xs leading-[1.55] m-0">Sağdaki bir metne, hücreye veya görsele tıklayın; kaynaktaki konumu burada görünür.</p>}
    {hasSelection && evidences.length === 0 && <p className="text-xs leading-[1.55] text-warn m-0">Seçili içerik için kaynak konumu kaydedilmemiş.</p>}
    {pages.length > 0 && current ? <div className="grid gap-2">
      <div className="flex items-center justify-between text-xs font-semibold gap-2">
        <Button variant="ghost" type="button" className={reviewAction} disabled={index === 0} onClick={() => setPage(pages[index - 1].page_number)}>← Önceki</Button>
        <span aria-live="polite">Sayfa {current.page_number} / {pages.length}</span>
        <Button variant="ghost" type="button" className={reviewAction} disabled={index >= pages.length - 1} onClick={() => setPage(pages[index + 1].page_number)}>Sonraki →</Button>
      </div>
      {failed === current.render_url ? <div className="text-center border border-dashed border-line rounded-sm text-faint text-xs bg-paper py-6 px-3">Sayfa görüntüsü yüklenemedi. Orijinali indirerek kontrol edin.</div> :
        <div className="relative leading-0 bg-paper border border-solid border-line shadow-none [&_img]:w-full [&_img]:h-auto [&_img]:block">
          <img src={absolute(current.render_url)} alt={`Kaynak belge, sayfa ${current.page_number}`} onError={() => setFailed(current.render_url)} />
          {boxes.map((e) => <span key={e.id} className={cn(`absolute border-[2px] border-solid border-accent bg-accent-soft rounded-xs pointer-events-none${e.id === active?.id ? " border-warn bg-warn-soft [box-shadow:0_0_0_1px_var(--warn-line)]" : ""}`)} aria-hidden style={{
            left: `${e.locator.bbox!.x * 100}%`, top: `${e.locator.bbox!.y * 100}%`,
            width: `${e.locator.bbox!.width * 100}%`, height: `${e.locator.bbox!.height * 100}%`,
          }} />)}
        </div>}
      {active?.locator.kind === "pdf_page" && !active.locator.bbox && <p className="text-faint text-xs leading-[1.55] m-0">Bu kayıt için sayfadaki bölge bilinmiyor; yalnızca sayfa gösteriliyor.</p>}
    </div> : active?.locator.kind === "image_region" ? null :
      <div className="bg-paper border border-dashed border-line rounded-sm text-xs [&_p]:mt-1 [&_p]:mb-0 [&_p]:text-faint py-3 px-4 [&_p]:mx-0">
        <strong>{active ? locatorLabel(active.locator) : "Konum seçilmedi"}</strong>
        <p>Bu kaynak biçimi için sayfa görüntüsü üretilmiyor. Konumu orijinal dosyada açarak kontrol edin; yukarıdaki bağlantı doğrulanmış özgün dosyayı indirir.</p>
      </div>}
    {active && (developerMode || active.locator.kind === "image_region") && <details className="[&_summary]:cursor-pointer [&_summary]:text-xs [&_summary]:font-semibold [&_summary]:text-ink2" open={active.locator.kind === "image_region"}>
      <summary>{developerMode ? "Kaynak izi ayrıntıları" : "Kaynak görseli"}</summary>
      <EvidenceView key={active.id} evidence={active} snapshot={ws.snapshot} versionId={ws.source.document_version_id ?? undefined} />
    </details>}
  </aside>;
}

export function ReviewWorkspace({ documentId, onSaved, mode, onDirtyChange, view = "read", onRead }: {
  view?: "read" | "history"; onRead?: () => void;
  documentId: string; onSaved: () => void; mode: Mode | null; onDirtyChange?: (dirty: boolean) => void;
}) {
  const developerMode = useDeveloperMode();
  const [ws, setWs] = useState<Workspace | null>(null);
  const [load, setLoad] = useState<{ status: "idle" | "loading" | "ready" | "error"; message: string }>({ status: "idle", message: "" });
  const [viewRevision, setViewRevision] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [section, setSection] = useState<SectionKey>("text");
  useEffect(() => { if (!developerMode && section === "chat") setSection("text"); }, [developerMode, section]);
  const [query, setQuery] = useState("");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [uncertaintyDrafts, setUncertaintyDrafts] = useState<Record<string, string>>({});
  const [selection, setSelection] = useState<Selection | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [tableId, setTableId] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<PreviewState>({ status: "idle" });
  const [sourceChecked, setSourceChecked] = useState(false);
  const [save, setSave] = useState<SaveState>({ status: "idle", message: "" });
  const [conflict, setConflict] = useState("");
  const [commitOpen, setCommitOpen] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(true);
  const [adoptions, setAdoptions] = useState<Record<string, Adoption>>({});

  const loadCtl = useRef<AbortController | null>(null);
  const previewCtl = useRef<AbortController | null>(null);
  const saveCtl = useRef<AbortController | null>(null);
  const previewSeq = useRef(0);
  const saveSeq = useRef(0);
  const loadSeq = useRef(0);
  const previewBusy = useRef(false);
  const saveBusy = useRef(false);
  const operation = useRef<{ id: string; at: string; sig: string } | null>(null);
  const sourceRef = useRef<HTMLElement | null>(null);
  const onSavedRef = useRef(onSaved);
  const onDirtyRef = useRef(onDirtyChange);
  onSavedRef.current = onSaved;
  onDirtyRef.current = onDirtyChange;
  const baseId = useId();

  const abortAll = useCallback(() => {
    loadCtl.current?.abort(); previewCtl.current?.abort(); saveCtl.current?.abort();
    loadSeq.current += 1; previewSeq.current += 1; saveSeq.current += 1;
    previewBusy.current = false; saveBusy.current = false;
  }, []);
  const invalidatePreview = useCallback(() => {
    previewCtl.current?.abort(); previewSeq.current += 1; previewBusy.current = false;
    setPreview({ status: "idle" }); setSourceChecked(false);
    setSave((state) => state.status === "saving" ? state : { status: "idle", message: "" });
  }, []);
  const resetDraftState = useCallback(() => {
    setDrafts({}); setUncertaintyDrafts({}); setAdoptions({}); setPreview({ status: "idle" }); setSourceChecked(false); setConflict("");
    setSave({ status: "idle", message: "" }); operation.current = null; setSelection(null); setActiveEvidence(null);
  }, []);

  // Document or mode change: drop everything that belongs to the previous document.
  useEffect(() => {
    abortAll(); resetDraftState(); setWs(null); setViewRevision(null); setQuery(""); setSection("text");
    return () => abortAll();
  }, [documentId, mode, abortAll, resetDraftState]);

  useEffect(() => {
    if (mode !== "live") { setLoad({ status: "idle", message: "" }); return; }
    const ctl = new AbortController();
    loadCtl.current = ctl;
    const seq = ++loadSeq.current;
    setLoad({ status: "loading", message: "" });
    const url = `${API}/v1/documents/${encodeURIComponent(documentId)}/review${viewRevision ? `?revision_id=${encodeURIComponent(viewRevision)}` : ""}`;
    request<unknown>(url, mode, { signal: ctl.signal }).then((data) => {
      if (ctl.signal.aborted || seq !== loadSeq.current) return;
      if (!isWorkspace(data) || data.document_id !== documentId) throw new Error("İnceleme verisi beklenen biçimde değil.");
      setWs({ ...data, warnings: data.warnings ?? [] });
      setLoad({ status: "ready", message: "" });
    }).catch((error: unknown) => {
      if (ctl.signal.aborted || seq !== loadSeq.current) return;
      setLoad({ status: "error", message: error instanceof HttpError && error.status === 404
        ? "Bu doküman için henüz incelenebilir içerik yok." : error instanceof Error ? error.message : "İnceleme verisi alınamadı." });
    });
    return () => ctl.abort();
  }, [documentId, mode, viewRevision, reloadTick]);

  const index = useMemo(() => {
    if (!ws) return null;
    const nodes = new Map(ws.snapshot.structure.map((node) => [node.id, node]));
    const fieldsByNode = new Map<string, ReviewField[]>();
    for (const field of ws.fields) fieldsByNode.set(field.node_id, [...(fieldsByNode.get(field.node_id) ?? []), field]);
    const evidenceById = new Map(ws.snapshot.evidence.map((item) => [item.id, item]));
    const blocks = readingOrder(ws.snapshot, nodes);
    const grids = new Map<string, Grid>();
    for (const { node } of blocks) if (node.kind === "table") grids.set(node.id, buildGrid(node, fieldsByNode.get(node.id) ?? []));
    const ordered = [...ws.history].map((entry, i) => ({ entry, i }))
      .sort((a, b) => new Date(a.entry.created_at).getTime() - new Date(b.entry.created_at).getTime() || a.i - b.i);
    const numbers = new Map(ordered.map(({ entry }, i) => [entry.revision_id, i + 1]));
    return { nodes, fieldsByNode, evidenceById, blocks, grids, numbers, gaps: computeGaps(ws, fieldsByNode, blocks) };
  }, [ws]);

  const displayedRevision = ws?.snapshot.knowledge_revision.id ?? "";
  const viewLatest = !!ws && displayedRevision === ws.latest_revision_id;
  const saving = save.status === "saving";
  const locked = saving || load.status === "loading";

  const evaluated = useMemo(() => {
    const changes: { field: ReviewField; after: Scalar; visualUncertainties?: string[] }[] = [];
    const invalid: ReviewField[] = [];
    if (ws) for (const field of ws.fields) {
      const draft = drafts[field.field_id];
      const notes = uncertaintyDrafts[field.field_id];
      if (draft === undefined && notes === undefined) continue;
      const visualUncertainties = notes === undefined ? undefined : notes.split("\n").map((s) => s.trim()).filter(Boolean);
      if (visualUncertainties && (visualUncertainties.length > 20 || visualUncertainties.some((s) => s.length > 500))) {
        invalid.push(field); continue;
      }
      const result = compute(field, draft ?? toRaw(field.value));
      const notesChanged = notes !== undefined && JSON.stringify(visualUncertainties) !== JSON.stringify(storedVisualUncertainties(ws.snapshot, field.node_id));
      if (!result.ok) invalid.push(field); else if (result.changed || notesChanged) changes.push({ field, after: result.value, visualUncertainties });
    }
    return { changes, invalid };
  }, [ws, drafts, uncertaintyDrafts]);

  const dirtyCount = evaluated.changes.length + evaluated.invalid.length;

  useEffect(() => { onDirtyRef.current?.(dirtyCount > 0); }, [dirtyCount]);
  useEffect(() => () => onDirtyRef.current?.(false), []);
  useEffect(() => {
    if (dirtyCount === 0) return;
    const handler = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirtyCount]);

  const confirmDiscard = () => dirtyCount === 0 || window.confirm(DISCARD_MESSAGE);

  const setDraft = useCallback((field: ReviewField, value: Draft) => {
    invalidatePreview();
    setDrafts((current) => {
      const next = { ...current };
      if (value === toRaw(field.value)) delete next[field.field_id]; else next[field.field_id] = value;
      return next;
    });
  }, [invalidatePreview]);
  const revert = useCallback((field: ReviewField) => {
    invalidatePreview();
    setDrafts((current) => { const next = { ...current }; delete next[field.field_id]; return next; });
    setAdoptions((current) => { const next = { ...current }; delete next[field.field_id]; return next; });
    setUncertaintyDrafts((current) => { const next = { ...current }; delete next[field.field_id]; return next; });
  }, [invalidatePreview]);
  const setUncertaintyDraft = useCallback((field: ReviewField, value: string) => {
    invalidatePreview(); setUncertaintyDrafts((all) => ({ ...all, [field.field_id]: value }));
  }, [invalidatePreview]);
  const revertAll = () => {
    if (!dirtyCount || !window.confirm("Tüm taslak değişiklikler geri alınsın mı?")) return;
    invalidatePreview(); setDrafts({}); setUncertaintyDrafts({}); setAdoptions({}); setConflict("");
  };
  const adoptProposal = useCallback((field: ReviewField, description: string, proposal: LocalVisualProposalData): boolean => {
    if (!ws || !viewLatest || !ws.can_edit || !field.editable || locked || description.trim() === "") return false;
    if (proposal.revision_id !== ws.snapshot.knowledge_revision.id || proposal.snapshot_sha256 !== ws.snapshot_sha256 || proposal.node_id !== field.node_id) return false;
    const current = drafts[field.field_id] ?? toRaw(field.value);
    if (typeof current === "boolean") return false;
    if (current.trim() !== "" && current !== description &&
      !window.confirm("Bu alanda zaten bir açıklama veya taslak var. Yerel model önerisi bunun yerine yazılsın mı? Mevcut taslak metni değiştirilir (özgün değer korunur ve “Geri al” ile dönülebilir).")) return false;
    setDraft(field, description);
    setAdoptions((all) => ({ ...all, [field.field_id]: { proposal, description, adopted_at: new Date().toISOString() } }));
    setUncertaintyDrafts((all) => {
      const existing = all[field.field_id]?.split("\n").map((s) => s.trim()).filter(Boolean)
        ?? storedVisualUncertainties(ws.snapshot, field.node_id);
      return { ...all, [field.field_id]: [...new Set([...existing, ...proposal.uncertainties])].join("\n") };
    });
    return true;
  }, [ws, viewLatest, locked, drafts, setDraft]);

  const selectContent = useCallback((next: Selection, reveal = false) => {
    setSelection(next); setActiveEvidence(next.evidenceId ?? null);
    if (next.nodeId && index?.nodes.get(next.nodeId)?.kind === "table") setTableId(next.nodeId);
    if (reveal) {
      setSourceOpen(true);
      window.requestAnimationFrame(() => sourceRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    }
  }, [index]);
  const openSection = useCallback((target: SectionKey, nodeId?: string) => {
    setSection(target); setQuery("");
    if (nodeId && index?.nodes.get(nodeId)?.kind === "table") setTableId(nodeId);
    if (nodeId) window.setTimeout(() => document.getElementById(`rw-node-${nodeId}`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 60);
  }, [index]);

  const selectedEvidence = useMemo(() => {
    if (!ws || !index || !selection) return [] as Evidence[];
    const field = selection.fieldId ? index.fieldsByNode.get(selection.nodeId)?.find((f) => f.field_id === selection.fieldId) : undefined;
    const node = index.nodes.get(selection.nodeId);
    const ids = field?.evidence_ids.length ? field.evidence_ids : node ? nodeEvidenceIds(node) : [];
    return Array.from(new Set(ids)).map((id) => index.evidenceById.get(id)).filter((item): item is Evidence => !!item);
  }, [ws, index, selection]);
  const activeEvidenceItem = selectedEvidence.find((e) => e.id === activeEvidence) ?? selectedEvidence[0];
  useEffect(() => {
    if (activeEvidenceItem?.locator.kind === "pdf_page") setPage(activeEvidenceItem.locator.page_number);
  }, [activeEvidenceItem?.id, activeEvidenceItem?.locator]);
  useEffect(() => {
    if (ws && ws.source.pages.length && !ws.source.pages.some((p) => p.page_number === page)) setPage(ws.source.pages[0].page_number);
  }, [ws, page]);

  function goToRevision(id: string) {
    if (saving || !ws || id === displayedRevision || !confirmDiscard()) return;
    abortAll(); resetDraftState();
    setViewRevision(id === ws.latest_revision_id ? null : id);
    onRead?.();
    if (id === ws.latest_revision_id && viewRevision === null) setReloadTick((t) => t + 1);
  }
  function loadCurrent() {
    if (saving || !window.confirm("Güncel içerik yüklenecek ve taslak değişiklikleriniz silinecek. Önce taslağı indirmediyseniz kaybolur. Devam edilsin mi?")) return;
    abortAll(); resetDraftState(); setViewRevision(null); setReloadTick((t) => t + 1);
  }

  const canSubmit = !!ws && viewLatest && ws.can_edit && evaluated.changes.length > 0 && evaluated.invalid.length === 0 &&
    reviewer.trim() !== "" && reason.trim() !== "";

  function buildBody(): RequestBody | null {
    if (!ws || typeof crypto === "undefined" || typeof crypto.randomUUID !== "function") return null;
    const base = {
      base_revision_id: ws.snapshot.knowledge_revision.id, base_snapshot_sha256: ws.snapshot_sha256,
      reviewer_id: reviewer.trim(), reason: [reason.trim(), ...evaluated.changes.flatMap(({ field, after }) => {
        const adoption = adoptions[field.field_id];
        return adoption && adoption.description === after ? [`Yerel öneri: ${adoption.proposal.id} (${adoption.proposal.profile_id}); kaynakla ayrıca incelendi.`] : [];
      })].join("\n"),
      changes: evaluated.changes.map(({ field, after, visualUncertainties }): ChangeBody => {
        return { field_id: field.field_id, before: field.value, after,
          ...(field.kind === "description" && visualUncertainties !== undefined ? { visual_uncertainties: visualUncertainties } : {}) };
      }),
    };
    const sig = JSON.stringify(base);
    // Retries of the identical payload keep the same operation id and time; any payload change starts a new operation.
    if (!operation.current || operation.current.sig !== sig) operation.current = { id: crypto.randomUUID(), at: new Date().toISOString(), sig };
    return { ...base, operation_id: operation.current.id, occurred_at: operation.current.at };
  }
  const failure = (error: unknown, fallback: string) => {
    if (error instanceof HttpError && error.status === 409) {
      setConflict("Belge siz düzenlerken değişti veya taslağın dayandığı değerler artık geçerli değil. Taslağınız korundu.");
      return `Çakışma: ${error.message}`;
    }
    return error instanceof Error ? error.message : fallback;
  };

  async function runPreview() {
    if (mode !== "live" || !canSubmit || previewBusy.current || saveBusy.current) return;
    const body = buildBody();
    if (!body) { setPreview({ status: "error", message: "Bu tarayıcı güvenli işlem kimliği üretemiyor; sayfayı güvenli bağlamda açın." }); return; }
    const ctl = new AbortController();
    previewCtl.current = ctl; previewBusy.current = true;
    const seq = ++previewSeq.current;
    setPreview({ status: "loading" }); setSourceChecked(false); setSave({ status: "idle", message: "" });
    try {
      const data = await request<Preview>(`${API}/v1/documents/${encodeURIComponent(documentId)}/reviews/preview`, mode,
        { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal: ctl.signal });
      if (seq !== previewSeq.current) return;
      const matches = data.base_revision_id === body.base_revision_id && data.snapshot_sha256 === body.base_snapshot_sha256 &&
        data.changes.length === body.changes.length && body.changes.every((change, i) =>
          data.changes[i].field_id === change.field_id && Object.is(data.changes[i].after, change.after) &&
          JSON.stringify(data.changes[i].visual_uncertainties ?? null) === JSON.stringify(change.visual_uncertainties ?? null));
      setPreview(matches ? { status: "ready", data, body } :
        { status: "error", message: "Sunucu önizlemesi taslağınızla eşleşmiyor. Kaydedilmedi; yeniden önizleyin." });
    } catch (error) {
      if (seq !== previewSeq.current || ctl.signal.aborted) return;
      setPreview({ status: "error", message: failure(error, "Önizleme alınamadı. Taslağınız korundu.") });
    } finally {
      if (seq === previewSeq.current) previewBusy.current = false;
    }
  }

  async function runSave() {
    if (mode !== "live" || preview.status !== "ready" || !sourceChecked || saveBusy.current || previewBusy.current) return;
    const ctl = new AbortController();
    saveCtl.current = ctl; saveBusy.current = true;
    const seq = ++saveSeq.current;
    setSave({ status: "saving", message: "Değişiklikler kaydediliyor…" });
    try {
      const result = await request<SaveResult>(`${API}/v1/documents/${encodeURIComponent(documentId)}/reviews`, mode, {
        method: "POST", headers: { "content-type": "application/json" }, signal: ctl.signal,
        body: JSON.stringify({ ...preview.body, preview_id: preview.data.proposal_id, confirmed_source: true }),
      });
      if (seq !== saveSeq.current) return;
      setDrafts({}); setUncertaintyDrafts({}); setAdoptions({}); setPreview({ status: "idle" }); setSourceChecked(false); setReason(""); setConflict("");
      operation.current = null; setCommitOpen(false);
      setSave({ status: "saved", message: result.inserted ? "Değişiklikler kaydedildi. Değiştirdiğiniz alanlar kaynakla kontrol edilmiş olarak işaretlendi; belgenin tamamının doğruluğu onaylanmış sayılmaz."
        : "Bu işlem daha önce kaydedilmişti; yeni düzenleme eklenmedi." });
      onSavedRef.current();
      setViewRevision(null); setReloadTick((t) => t + 1);
    } catch (error) {
      if (seq !== saveSeq.current || ctl.signal.aborted) return;
      setSave({ status: "error", message: failure(error, "Kaydedilemedi. Taslağınız korundu; aynı işlemle tekrar deneyebilirsiniz.") });
    } finally {
      if (seq === saveSeq.current) saveBusy.current = false;
    }
  }

  function downloadDraft() {
    if (!ws) return;
    const payload = {
      format: "docgrain.review-draft", document_id: documentId, base_revision_id: displayedRevision,
      base_snapshot_sha256: ws.snapshot_sha256, exported_at: new Date().toISOString(),
      reviewer_id: reviewer.trim() || null, reason: reason.trim() || null,
      changes: evaluated.changes.map(({ field, after, visualUncertainties }) => ({ field_id: field.field_id, node_id: field.node_id, label: field.label, before: field.value, after, visual_uncertainties: visualUncertainties })),
      unparsed_drafts: evaluated.invalid.map((field) => ({ field_id: field.field_id, label: field.label, before: field.value, draft: drafts[field.field_id] })),
      // Only proposals whose text is still the drafted value; the save request never carries these.
      adopted_local_visual_proposals: evaluated.changes.flatMap(({ field, after }) => {
        const adoption = adoptions[field.field_id];
        return adoption && adoption.description === after
          ? [{ field_id: field.field_id, node_id: field.node_id, adopted_at: adoption.adopted_at, proposal: adoption.proposal }] : [];
      }),
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url; link.download = `docgrain-inceleme-taslagi.json`;
    document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const ctx: Ctx | null = index && ws ? {
    nodes: index.nodes, fieldsByNode: index.fieldsByNode, viewLatest, wsEditable: ws.can_edit, locked, drafts, query, selection,
    setDraft, revert, uncertaintyDrafts, setUncertaintyDraft, mode, snapshotSha256: ws.snapshot_sha256, adoptProposal, select: selectContent, openSection,
  } : null;

  if (mode === "demo") {
    return <div className={loadingWorkspace}><Empty title="Örnek belgelerde inceleme kapalı" detail="Örnek belgeler gösterilir; belge içeriği üretilmez ve değişiklik kaydedilemez. Bağlantı kurulduğunda burada kaynak ve içerik yan yana görünür." /></div>;
  }
  if (mode === null) return <div className={loadingWorkspace}><Empty title="Bağlanıyor…" detail="Çalışma modu doğrulandığında belge incelemesi açılır." /></div>;
  if (!ws || !index || !ctx) {
    return <div className={loadingWorkspace} aria-busy={load.status === "loading"}>
      {load.status === "error" ? <div role="alert"><Empty title="İnceleme açılamadı" detail={developerMode ? load.message : "Belge içeriği alınamadı. Bir süre sonra tekrar deneyin."} />
        <Button variant="ghost" type="button" className={reviewAction} onClick={() => setReloadTick((t) => t + 1)}>Tekrar dene</Button></div>
        : <div className="grid w-full gap-3" role="status"><Skeleton className="h-[74px] w-full rounded-lg bg-sheet" /><Skeleton className="h-[74px] w-full rounded-lg bg-sheet" /><Skeleton className="h-[74px] w-full rounded-lg bg-sheet" /><p className="text-faint">Belge ve kaynak yükleniyor…</p></div>}
    </div>;
  }

  const activeSection = view === "history" ? "history" : section;
  const sections = SECTIONS.filter(([key]) => key !== "history" && (developerMode || key !== "chat"));
  const counts: Record<SectionKey, number> = {
    text: index.blocks.filter(({ node }) => node.kind === "text_block" || node.kind === "list").length,
    tables: index.blocks.filter(({ node }) => node.kind === "table").length,
    visuals: index.blocks.filter(({ node }) => node.kind === "asset" || node.kind === "chart").length,
    gaps: index.gaps.length, history: ws.history.length, chat: 0,
  };
  const tabId = (key: SectionKey) => `${baseId}-tab-${key}`;
  const revNumber = index.numbers.get(displayedRevision);
  const currentEntry = ws.history.find((entry) => entry.revision_id === displayedRevision);

  return <RwContext.Provider value={ctx}>
    <div className="text-ink min-w-0 bg-ground min-h-[70vh] pt-0 pb-6 [&_button]:font-sans [&_input]:font-sans [&_textarea]:font-sans [&_select]:font-sans [&_:focus-visible]:[outline:2px_solid_var(--accent)] [&_:focus-visible]:[outline-offset:2px] px-0" aria-busy={load.status === "loading"}>
      <header className="sticky top-0 z-[20] grid grid-cols-[minmax(0,_1fr)_minmax(220px,_340px)] gap-y-1 gap-x-6 pt-3 pb-0 bg-[color-mix(in_srgb,_var(--ground)_94%,_transparent)] [backdrop-filter:blur(8px)] border-b border-solid border-b-line max-[1000px]:grid-cols-[minmax(0,_1fr)] max-[1000px]:pt-3 max-[1000px]:pb-0 max-[1000px]:static px-8 max-[1000px]:px-4">
        <div className="[&_h2]:font-semibold [&_h2]:text-[clamp(var(--text-lg),_2.2vw,_var(--text-2xl))] [&_h2]:leading-[1.15] [&_h2]:font-sans [&_h2]:wrap-anywhere [&_p]:text-ink2 [&_p]:text-xs [&_p]:flex [&_p]:flex-wrap [&_p]:gap-y-1 [&_p]:gap-x-2 [&_p]:items-center [&_h2]:my-1 [&_h2]:mx-0 [&_p]:m-0">
          <span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-accent">Belgeyi incele</span>
          <h2>{ws.source.filename}</h2>
          <p>Düzenleme {revNumber ?? "—"}{currentEntry ? ` · ${dateText(currentEntry.created_at)}` : ""}
            {viewLatest ? <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-accent-soft text-accent py-1 px-2">Güncel</span> : <span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-sheet text-faint py-1 px-2">Eski düzenleme · salt okunur</span>}</p>
        </div>
        {view !== "history" && <label className="self-center [&_input]:w-full [&_input]:border [&_input]:border-solid [&_input]:border-line [&_input]:rounded-pill [&_input]:bg-paper [&_input]:text-sm [&_input:focus]:border-accent [&_input:focus]:[box-shadow:0_0_0_3px_var(--accent-soft)] [&_input:focus]:[outline:none] [&_input]:py-2 [&_input]:px-3"><span className="absolute w-[1px] h-[1px] overflow-hidden [clip:rect(0_0_0_0)] whitespace-nowrap">Belgede ara</span>
          <Input type="search" value={query} placeholder="Metin, hücre veya açıklama ara…" onChange={(e) => setQuery(e.target.value)} /></label>}
        {view !== "history" && <nav className="col-[1_/_-1] overflow-x-auto [scrollbar-width:none] [&_[role='tablist']]:flex [&_[role='tablist']]:min-w-[max-content] [&_button]:relative [&_button]:bg-transparent [&_button]:border-0 [&_button]:text-sm [&_button]:font-semibold [&_button]:text-ink2 [&_button]:inline-flex [&_button]:items-center [&_button_i]:font-semibold [&_button_i]:text-2xs [&_button_i]:font-mono [&_button_i]:not-italic [&_button_i]:rounded-pill [&_button_i]:bg-line2 [&_button_i]:text-faint [&_button::after]:content-[''] [&_button::after]:absolute [&_button::after]:left-[10px] [&_button::after]:right-[10px] [&_button::after]:bottom-[-1px] [&_button::after]:h-[3px] [&_button::after]:rounded-[var(--radius-xs)_var(--radius-xs)_0_0] [&_button::after]:bg-accent [&_button::after]:[transform:scaleX(0)] [&_button::after]:motion-safe:transition-colors [&_button::after]:motion-safe:duration-150 [&_button[aria-selected='true']]:text-accent [&_button[aria-selected='true']_i]:bg-accent-soft [&_button[aria-selected='true']_i]:text-accent [&_button[aria-selected='true']::after]:[transform:scaleX(1)] [&_button:hover]:text-ink max-[1000px]:sticky max-[1000px]:top-0 max-[1000px]:z-[20] max-[1000px]:bg-ground motion-reduce:[&_button::after]:transition-none [&_[role='tablist']]:gap-1 [&_button]:gap-2 [&_button]:p-3 [&_button_i]:p-1" aria-label="Belge bölümleri">
          <div role="tablist" aria-label="Bölümler" onKeyDown={(e) => {
            if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
            const at = sections.findIndex(([key]) => key === section);
            const next = sections[(at + (e.key === "ArrowRight" ? 1 : sections.length - 1)) % sections.length][0];
            setSection(next); document.getElementById(tabId(next))?.focus();
          }}>
            {sections.map(([key, label]) => <Button variant="ghost" type="button" role="tab" key={key} id={tabId(key)} aria-selected={section === key}
              aria-controls={`${baseId}-panel`} tabIndex={section === key ? 0 : -1} onClick={() => setSection(key)}>
              {label}{key !== "chat" && <i>{counts[key]}</i>}</Button>)}
          </div>
        </nav>}
      </header>

      {!viewLatest && <div className="mt-3 mb-0 border border-solid border-line border-l-[4px] rounded-sm text-xs flex flex-wrap gap-y-2 gap-x-3 items-center justify-between border-l-warn bg-warn-soft mx-8 py-3 px-4 max-[1000px]:mx-4 [&_p]:m-0" role="status">Eski bir düzenlemeyi görüntülüyorsunuz; düzenleme kapalı.
        <Button variant="ghost" type="button" className={reviewAction} onClick={() => goToRevision(ws.latest_revision_id)} disabled={locked}>Güncel içeriğe dön</Button></div>}
      {viewLatest && !ws.can_edit && <div className="mt-3 mb-0 border border-solid border-line border-l-[4px] border-l-accent rounded-sm bg-paper text-xs flex flex-wrap gap-y-2 gap-x-3 items-center justify-between mx-8 py-3 px-4 max-[1000px]:mx-4 [&_p]:m-0" role="status">Bu belge şu an düzenlemeye kapalı; içerik yalnızca okunabilir.</div>}
      {load.status === "error" && <div className="mt-3 mb-0 border border-solid border-line border-l-[4px] rounded-sm text-xs flex flex-wrap gap-y-2 gap-x-3 items-center justify-between border-l-warn bg-warn-soft mx-8 py-3 px-4 max-[1000px]:mx-4 [&_p]:m-0" role="alert">{developerMode ? load.message : "Belge içeriği alınamadı. Tekrar deneyin."}
        <Button variant="ghost" type="button" className={reviewAction} onClick={() => setReloadTick((t) => t + 1)}>Tekrar dene</Button></div>}
      {save.status === "saved" && <div className="mt-3 mb-0 border border-solid border-line border-l-[4px] rounded-sm text-xs flex flex-wrap gap-y-2 gap-x-3 items-center justify-between border-l-ok bg-ok-soft mx-8 py-3 px-4 max-[1000px]:mx-4 [&_p]:m-0" role="status">{save.message}</div>}
      {view !== "history" && <p className="mt-3 mb-1 max-w-[78ch] text-ink2 text-xs leading-[1.6] mx-8 max-[1000px]:mx-4">İçeriği özgün dosyayla karşılaştırın. Değişikliklerinizi gözden geçirip kaydedin; her kayıt düzenleme geçmişine eklenir.</p>}

      {view !== "history" && <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal hidden max-[1000px]:block max-[1000px]:mt-3 max-[1000px]:mb-0 max-[1000px]:border max-[1000px]:border-solid max-[1000px]:border-line max-[1000px]:rounded-sm max-[1000px]:bg-paper max-[1000px]:text-xs max-[1000px]:font-semibold max-[1000px]:mx-4 max-[1000px]:py-2 max-[1000px]:px-3" aria-expanded={sourceOpen} onClick={() => setSourceOpen(!sourceOpen)}>
        {sourceOpen ? "Kaynağı gizle" : "Kaynağı göster"}</Button>}
      <div className={cn(`grid grid-cols-[minmax(300px,_.85fr)_minmax(0,_1.3fr)] pt-4 pb-0 [align-items:start] max-[1000px]:grid-cols-[minmax(0,_1fr)] max-[1000px]:pt-3 max-[1000px]:pb-0 gap-6 px-8 max-[1000px]:px-4${sourceOpen && view !== "history" ? "" : " grid-cols-[minmax(0,_1fr)]"}`)}>
        {sourceOpen && view !== "history" && <SourcePanel ws={ws} evidences={selectedEvidence} activeId={activeEvidenceItem?.id ?? null} setActiveId={setActiveEvidence}
          page={page} setPage={setPage} hasSelection={!!selection} panelRef={sourceRef} />}
        <div className="min-w-0 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300 motion-reduce:animate-none" id={`${baseId}-panel`} role="tabpanel" aria-label={view === "history" ? "Düzenleme geçmişi" : undefined} aria-labelledby={view === "history" ? undefined : tabId(section)}>
          {activeSection === "text" && <TextPanel blocks={index.blocks} />}
          {activeSection === "tables" && <TablesPanel blocks={index.blocks} tableId={tableId} setTableId={setTableId} grids={index.grids} />}
          {activeSection === "visuals" && <VisualsPanel blocks={index.blocks} snapshot={ws.snapshot} />}
          {activeSection === "gaps" && <GapsPanel gaps={index.gaps} />}
          {activeSection === "chat" && <RevisionChat snapshot={ws.snapshot} snapshotSha256={ws.snapshot_sha256} versionId={ws.source.document_version_id ?? undefined} revisionLabel={revNumber ? String(revNumber) : undefined} mode={mode} />}
          {activeSection === "history" && <HistoryPanel ws={ws} numbers={index.numbers} displayed={displayedRevision} locked={locked} onView={goToRevision} />}
        </div>
      </div>

      {(dirtyCount > 0 || conflict) && <section className="sticky bottom-0 z-[25] mt-4 mb-0 flex flex-col border border-solid border-ink rounded-[var(--radius-sm)_var(--radius-sm)_0_0] bg-paper shadow-2 max-[1000px]:mt-3 max-[1000px]:mb-0 max-[1000px]:rounded-none mx-8 max-[1000px]:mx-0" aria-label="Taslak değişiklikler">
        {commitOpen && <div className="max-h-[62vh] overflow-auto grid gap-3 p-4" id={`${baseId}-commit`}>
          {conflict && <div className="border border-solid border-line border-l-[4px] rounded-sm text-xs flex flex-wrap gap-y-2 gap-x-3 items-center justify-between border-l-warn bg-warn-soft py-3 px-4 max-[1000px]:mx-4 m-0 [&_p]:m-0" role="alert"><p>{developerMode ? conflict : "Belge siz düzenlerken değişmiş olabilir. Taslağı indirin ve güncel içeriği yükleyin."}</p>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="ghost" type="button" className={reviewAction} onClick={downloadDraft}>Taslağı indir</Button>
              <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal inline-flex items-center justify-center border border-solid rounded-sm bg-paper text-xs font-semibold no-underline cursor-pointer motion-safe:transition-colors motion-safe:duration-150 [&:hover:not(:disabled)]:border-accent [&:hover:not(:disabled)]:bg-accent-soft [&:disabled]:opacity-[.45] [&:disabled]:cursor-default border-warn text-warn gap-1 py-2 px-3" onClick={loadCurrent} disabled={saving}>Güncel içeriği yükle (taslak silinir)</Button>
            </div></div>}
          <div className="grid grid-cols-[minmax(160px,_1fr)_minmax(0,_2.5fr)] [&_label]:grid [&_label]:text-xs [&_label]:font-semibold [&_input]:border [&_input]:border-solid [&_input]:border-line [&_input]:rounded-sm [&_input]:text-sm [&_input]:resize-y [&_textarea]:border [&_textarea]:border-solid [&_textarea]:border-line [&_textarea]:rounded-sm [&_textarea]:text-sm [&_textarea]:resize-y max-[640px]:grid-cols-[minmax(0,_1fr)] gap-3 [&_label]:gap-1 [&_input]:p-2 [&_textarea]:p-2">
            <label>İnceleyen kişi<Input value={reviewer} autoComplete="off" disabled={locked}
              onChange={(e) => { invalidatePreview(); setReviewer(e.target.value); }} /></label>
            <label>Değişiklik nedeni<Textarea value={reason} rows={2} disabled={locked}
              onChange={(e) => { invalidatePreview(); setReason(e.target.value); }} /></label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal inline-flex items-center justify-center border border-solid rounded-sm text-xs font-semibold no-underline cursor-pointer motion-safe:transition-colors motion-safe:duration-150 [&:hover:not(:disabled)]:border-accent [&:disabled]:opacity-[.45] [&:disabled]:cursor-default bg-accent border-accent text-on-accent [&:hover:not(:disabled)]:bg-accent gap-1 py-2 px-3" disabled={!canSubmit || preview.status === "loading" || locked} onClick={() => void runPreview()}>
              {preview.status === "loading" ? "Önizleniyor…" : "Farkları önizle"}</Button>
            <span className="text-faint text-xs leading-[1.55] m-0">{!viewLatest || !ws.can_edit ? "Bu görünümde kayıt yapılamaz." : evaluated.invalid.length ? "Geçersiz değerleri düzeltin." :
              !reviewer.trim() || !reason.trim() ? "Önizleme için inceleyen kişi ve neden gerekli." : "Önizleme hiçbir şeyi kaydetmez."}</span>
          </div>
          {preview.status === "error" && <p className="mt-1 mb-0 text-danger text-xs mx-0" role="alert">{developerMode ? preview.message : "Önizleme alınamadı. Bilgileri kontrol edip tekrar deneyin."}</p>}
          {preview.status === "ready" && <div className="grid [&_h3]:font-semibold [&_h3]:text-md [&_h3]:font-sans [&_ul]:[list-style:none] [&_ul]:grid [&_li]:border [&_li]:border-solid [&_li]:border-line2 [&_li]:rounded-sm gap-3 [&_ul]:gap-2 [&_li]:py-2 [&_li]:px-3 [&_h3]:m-0 [&_ul]:m-0 [&_ul]:p-0">
            <h3>Kaydedilecek farklar</h3>
            {preview.data.warnings.map((warning, i) => <p key={i} className="text-xs leading-[1.55] text-warn m-0">{developerMode ? warning : "Kaydetmeden önce bu değişikliği özgün dosyayla kontrol edin."}</p>)}
            <ul>{preview.data.changes.map((change) => <li key={change.field_id}>
              <div className="flex flex-wrap items-center mb-2 gap-2"><strong>{change.label}</strong><span className="inline-flex items-center rounded-pill font-semibold text-2xs leading-[1.5] font-sans bg-line2 text-ink2 py-1 px-2">{KIND_LABEL[change.kind]}</span></div>
              <div className="[&_span]:block [&_span]:font-bold [&_span]:text-2xs [&_span]:font-mono [&_span]:tracking-[.1em] [&_span]:uppercase [&_span]:text-warn grid grid-cols-[1fr_1fr] [&_>_div]:rounded-xs [&_>_div]:min-w-0 [&_p]:mt-1 [&_p]:mb-0 [&_p]:font-normal [&_p]:text-sm [&_p]:leading-[1.55] [&_p]:font-serif [&_p]:whitespace-pre-wrap [&_p]:wrap-anywhere max-[640px]:grid-cols-[minmax(0,_1fr)] gap-2 [&_p]:mx-0 [&_>_div]:p-2">
                <div className="bg-warn-soft [&_p]:line-through [&_p]:[text-decoration-color:var(--warn-line)]"><span>Önce</span><p>{formatScalar(change.before)}</p></div>
                <div className="bg-accent-soft [&_span]:text-accent"><span>Sonra</span><p>{formatScalar(change.after)}</p></div>
              </div>
              {change.visual_uncertainties != null && <div className="[&_span]:block [&_span]:font-bold [&_span]:text-2xs [&_span]:font-mono [&_span]:tracking-[.1em] [&_span]:uppercase [&_span]:text-warn grid grid-cols-[1fr_1fr] [&_>_div]:rounded-xs [&_>_div]:min-w-0 [&_p]:mt-1 [&_p]:mb-0 [&_p]:font-normal [&_p]:text-sm [&_p]:leading-[1.55] [&_p]:font-serif [&_p]:whitespace-pre-wrap [&_p]:wrap-anywhere max-[640px]:grid-cols-[minmax(0,_1fr)] gap-2 [&_p]:mx-0 [&_>_div]:p-2">
                <div className="bg-warn-soft [&_p]:line-through [&_p]:[text-decoration-color:var(--warn-line)]"><span>Önce · belirsizlikler</span><p>{storedVisualUncertainties(ws.snapshot, change.node_id).join("\n") || "Not yok"}</p></div>
                <div className="bg-accent-soft [&_span]:text-accent"><span>Sonra · belirsizlikler</span><p>{change.visual_uncertainties.join("\n") || "Not yok"}</p></div>
              </div>}
              <div className="flex flex-wrap gap-y-1 gap-x-4 mt-2">
                <Button variant="ghost" type="button" className={sourceAction} onClick={() => selectContent({ nodeId: change.node_id, fieldId: change.field_id }, true)}>Kaynakta göster</Button>
                <Button variant="ghost" type="button" className={sourceAction} onClick={() => { selectContent({ nodeId: change.node_id, fieldId: change.field_id }); openSection(KIND_SECTION[change.kind], change.node_id); }}>İçerikte göster</Button>
              </div>
            </li>)}</ul>
            <label className="inline-flex items-start text-xs text-ink2 [&_input]:mt-1 [&_input]:accent-accent bg-accent-soft rounded-sm gap-2 py-2 px-3"><input type="checkbox" checked={sourceChecked} disabled={locked} onChange={(e) => setSourceChecked(e.target.checked)} />
              Bu değişiklikleri özgün kaynakla karşılaştırdım. Bu onay yalnızca değiştirilen alanlar içindir; belgenin tamamının doğruluğunu onaylamaz.</label>
            <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal inline-flex items-center justify-center border border-solid rounded-sm text-xs font-semibold no-underline cursor-pointer motion-safe:transition-colors motion-safe:duration-150 [&:hover:not(:disabled)]:border-accent [&:disabled]:opacity-[.45] [&:disabled]:cursor-default bg-accent border-accent text-on-accent [&:hover:not(:disabled)]:bg-accent gap-1 py-2 px-3" disabled={!sourceChecked || locked} onClick={() => void runSave()}>
              {saving ? "Kaydediliyor…" : "Değişiklikleri kaydet"}</Button>
          </div>}
          {save.status === "error" && <p className="mt-1 mb-0 text-danger text-xs mx-0" role="alert">{developerMode ? save.message : "Değişiklikler kaydedilemedi. Tekrar deneyin."}</p>}
        </div>}
        <div className="flex flex-wrap items-center gap-y-2 gap-x-3 bg-ink text-paper py-2 px-4">
          <strong aria-live="polite">{evaluated.changes.length} değişiklik taslakta{evaluated.invalid.length ? ` · ${evaluated.invalid.length} geçersiz değer` : ""}</strong>
          <span className="text-paper text-xs leading-[1.55] m-0">Henüz kaydedilmedi</span>
          <div className="flex flex-wrap items-center ml-auto max-[640px]:ml-0 gap-2">
            <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal inline-flex items-center justify-center border border-solid border-line-strong rounded-sm bg-transparent text-paper text-xs font-semibold no-underline cursor-pointer motion-safe:transition-colors motion-safe:duration-150 [&:hover:not(:disabled)]:border-accent [&:hover:not(:disabled)]:bg-accent-soft [&:disabled]:opacity-[.45] [&:disabled]:cursor-default [&:hover:not(:disabled)]:text-ink gap-1 py-2 px-3" onClick={downloadDraft}>Taslağı indir</Button>
            <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal inline-flex items-center justify-center border border-solid border-line-strong rounded-sm bg-transparent text-paper text-xs font-semibold no-underline cursor-pointer motion-safe:transition-colors motion-safe:duration-150 [&:hover:not(:disabled)]:border-accent [&:hover:not(:disabled)]:bg-accent-soft [&:disabled]:opacity-[.45] [&:disabled]:cursor-default [&:hover:not(:disabled)]:text-ink gap-1 py-2 px-3" onClick={revertAll} disabled={locked}>Tümünü geri al</Button>
            <Button variant="ghost" type="button" className="h-auto min-h-7 whitespace-normal inline-flex items-center justify-center border border-solid rounded-sm text-xs font-semibold no-underline cursor-pointer motion-safe:transition-colors motion-safe:duration-150 [&:hover:not(:disabled)]:border-accent [&:disabled]:opacity-[.45] [&:disabled]:cursor-default [&:hover:not(:disabled)]:text-ink bg-accent border-accent text-on-accent [&:hover:not(:disabled)]:bg-accent gap-1 py-2 px-3" aria-expanded={commitOpen} aria-controls={`${baseId}-commit`} onClick={() => setCommitOpen(!commitOpen)}>
              {commitOpen ? "Kayıt adımlarını gizle" : "Gözden geçir ve kaydet"}</Button>
          </div>
        </div>
      </section>}
    </div>
  </RwContext.Provider>;
}
