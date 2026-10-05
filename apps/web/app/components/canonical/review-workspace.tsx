"use client";

import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import "./review-workspace.css";
import { useDeveloperMode } from "../developer-mode";
import { RevisionChat } from "./revision-chat";
import { EvidenceView, type Cell, type Evidence, type Locator, type Node, type Snapshot } from "./inspector";
import { LocalVisualProposal, type LocalVisualProposalData } from "./local-visual-proposal";

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
  return editable ? <span className="rw-chip rw-chip-edit">Düzenlenebilir</span>
    : <span className="rw-chip rw-chip-lock" title={reason}>Salt okunur · {reason}</span>;
}
function Original({ value }: { value: Scalar }) {
  return <div className="rw-original"><span>Orijinal değer</span><p>{formatScalar(value)}</p></div>;
}
function ScalarInput({ field, label, multiline, onFocus }: {
  field: ReviewField; label: string; multiline?: boolean; onFocus?: () => void;
}) {
  const c = useCtx();
  const st = fieldState(c, field);
  if (!st) return null;
  const common = { "aria-label": label, "aria-invalid": st.error ? true : undefined, disabled: c.locked, onFocus };
  if (typeof field.value === "boolean") {
    return <select {...common} className="rw-input" value={String(st.raw)} onChange={(e) => c.setDraft(field, e.target.value === "true")}>
      <option value="true">Doğru</option><option value="false">Yanlış</option>
    </select>;
  }
  const text = String(st.raw);
  if (multiline) {
    return <textarea {...common} placeholder={field.kind === "description" ? "Anlamı henüz açıklanmadı. Kaynak görselde gördüğünüz bilgiyi yazın…" : undefined} className="rw-input rw-textarea" value={text} rows={Math.min(16, Math.max(3, text.split("\n").length + 1))}
      onChange={(e) => c.setDraft(field, e.target.value)} />;
  }
  return <input {...common} className="rw-input" value={text} inputMode={typeof field.value === "number" ? "decimal" : undefined}
    onChange={(e) => c.setDraft(field, e.target.value)} />;
}

function TextBlock({ node, field, compact }: { node: Node; field: ReviewField | null; compact?: boolean }) {
  const c = useCtx();
  const st = fieldState(c, field);
  const [editing, setEditing] = useState(false);
  const text = st ? (typeof st.raw === "boolean" ? formatScalar(st.raw) : st.raw) : node.text ?? "";
  const selected = c.selection?.nodeId === node.id;
  const target: Selection = { nodeId: node.id, fieldId: field?.field_id };
  return <article id={`rw-node-${node.id}`} className={`rw-block${compact ? " rw-block-compact" : ""}${selected ? " is-selected" : ""}${st?.changed ? " is-changed" : ""}`}
    onClick={() => c.select(target)}>
    <div className="rw-block-meta">
      {st ? <AccessChip editable={st.editable} reason={st.reason} /> : <span className="rw-chip rw-chip-lock">Salt okunur · bu içerik için düzenleme alanı yok</span>}
      {st?.changed && <span className="rw-chip rw-chip-draft">Taslakta değişti</span>}
    </div>
    {editing && st?.editable && field ? <ScalarInput field={field} label={field.label} multiline onFocus={() => c.select(target)} />
      : <p className="rw-prose">{text ? <Highlight text={text} query={c.query} /> : <span className="rw-empty-value">(boş)</span>}</p>}
    {st?.changed && field && <Original value={field.value} />}
    {st?.error && <p className="rw-error" role="alert">{st.error}</p>}
    <div className="rw-block-actions">
      <button type="button" className="rw-link" onClick={(e) => { e.stopPropagation(); c.select(target, true); }}>Kaynakta göster</button>
      {st?.editable && field && <button type="button" className="rw-link" aria-pressed={editing} disabled={c.locked}
        onClick={(e) => { e.stopPropagation(); c.select(target); setEditing(!editing); }}>{editing ? "Düzenlemeyi kapat" : "Düzenle"}</button>}
      {st?.changed && field && <button type="button" className="rw-link rw-link-warn" disabled={c.locked}
        onClick={(e) => { e.stopPropagation(); c.revert(field); }}>Geri al</button>}
    </div>
  </article>;
}
function ListView({ node }: { node: Node }) {
  const c = useCtx();
  const items = (node.children ?? []).map((id) => c.nodes.get(id)).filter((item): item is Node => !!item);
  const textField = (n: Node) => c.fieldsByNode.get(n.id)?.find((f) => f.kind === "text") ?? null;
  if (!items.length) return <TextBlock node={node} field={textField(node)} />;
  const Tag: "ol" | "ul" = node.ordered ? "ol" : "ul";
  return <Tag className="rw-list">{items.map((item) => <li key={item.id}>
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
    return <div className="rw-flow">{hits.map(({ node, trail }) => <div key={node.id} className="rw-hit">
      {trail.length > 0 && <p className="rw-trail">{trail.join(" › ")}</p>}
      {node.kind === "list" ? <ListView node={node} /> : <TextBlock node={node} field={textField(node)} />}
    </div>)}</div>;
  }
  const visible = blocks.filter(({ node }) => node.kind !== "section" || node.heading || node.title);
  if (!visible.length) return <Empty title="Metin bulunamadı" detail="Bu içerikte okunabilir metin içeriği yok." />;
  return <div className="rw-flow">{visible.map(({ node, depth }) => {
    if (node.kind === "section") {
      const Heading = (`h${Math.min(5, Math.max(3, (node.level ?? depth) + 2))}`) as "h3" | "h4" | "h5";
      const field = textField(node);
      const st = fieldState(c, field);
      return <section key={node.id} id={`rw-node-${node.id}`}>
        <Heading className="rw-heading">{field ? String(c.drafts[field.field_id] ?? field.value) : node.heading || node.title}</Heading>
        {field && st?.editable && <details><summary>Başlığı düzenle</summary>
          <ScalarInput field={field} label="Bölüm başlığı" onFocus={() => c.select({ nodeId: node.id, fieldId: field.field_id })} />
          {st.changed && <><Original value={field.value} /><button type="button" className="rw-link" onClick={() => c.revert(field)}>Geri al</button></>}
        </details>}
        <button type="button" className="rw-link" onClick={() => c.select({ nodeId: node.id, fieldId: field?.field_id }, true)}>Başlığı kaynakta göster</button>
      </section>;
    }
    if (node.kind === "list") return <ListView key={node.id} node={node} />;
    if (node.kind === "table") {
      const edits = (c.fieldsByNode.get(node.id) ?? []).filter((f) => c.drafts[f.field_id] !== undefined).length;
      return <div className="rw-ref" key={node.id}><div><span className="rw-kicker">Tablo</span><strong>{nodeTitle(node, "Adsız tablo")}</strong>
        <small>{node.rows?.length ?? 0} satır{edits ? ` · ${edits} hücre taslakta` : ""}</small></div>
        <button type="button" className="rw-btn" onClick={() => c.openSection("tables", node.id)}>Tabloyu aç</button></div>;
    }
    if (node.kind === "asset" || node.kind === "chart") {
      return <div className="rw-ref" key={node.id}><div><span className="rw-kicker">{node.kind === "chart" ? "Grafik" : "Görsel"}</span>
        <strong>{node.description?.trim() ? node.caption || node.description : "Açıklama yok — ekle"}</strong></div>
        <button type="button" className="rw-btn" onClick={() => c.openSection("visuals", node.id)}>Görseli aç</button></div>;
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
  return <div className={`rw-cell${hit ? " is-hit" : ""}${active ? " is-active" : ""}${st?.changed ? " is-changed" : ""}${st?.error ? " is-invalid" : ""}`}>
    {st?.editable && slot.field ? <ScalarInput field={slot.field} label={label} multiline={typeof slot.field.value === "string" && slot.field.value.includes("\n")}
      onFocus={() => target && c.select(target)} />
      : <button type="button" className="rw-cell-read" aria-label={`${label}: ${text || "boş"}`} onClick={() => target && c.select(target)}>
        {text ? <Highlight text={text} query={c.query} /> : <span className="rw-empty-value">·</span>}
      </button>}
    {slot.cell.formula && <small className="rw-cell-note">ƒ {slot.cell.formula}</small>}
    {st && !st.editable && <small className="rw-cell-note rw-cell-lock">Salt okunur</small>}
    {st?.changed && slot.field && <small className="rw-cell-note rw-cell-orig">Orijinal: {formatScalar(slot.field.value)}</small>}
    {st?.error && <small className="rw-cell-note rw-error" role="alert">{st.error}</small>}
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
  return <div className="rw-tables">
    <div className="rw-table-nav" role="group" aria-label="Tablolar">
      {shown.map((t, index) => {
        const edits = (c.fieldsByNode.get(t.node.id) ?? []).filter((f) => c.drafts[f.field_id] !== undefined).length;
        return <button type="button" key={t.node.id} className="rw-table-pick" aria-pressed={t.node.id === current.node.id} onClick={() => setTableId(t.node.id)}>
          <span className="rw-kicker">Tablo {index + 1}</span><strong>{nodeTitle(t.node, "Adsız tablo")}</strong>
          <small>{t.node.rows?.length ?? 0} × {Math.max(0, ...(t.node.rows ?? []).map((r) => r.length))}{edits ? ` · ${edits} değişiklik` : ""}</small>
        </button>;
      })}
    </div>
    <section className="rw-table-card" id={`rw-node-${current.node.id}`}>
      <header>
        <div>{current.trail.length > 0 && <p className="rw-trail">{current.trail.join(" › ")}</p>}
          <h3>{nodeTitle(current.node, "Adsız tablo")}</h3></div>
        <label className="rw-check"><input type="checkbox" checked={header} onChange={(e) => setHeaderOverride({ ...headerOverride, [current.node.id]: e.target.checked })} />
          İlk satır sütun başlığı</label>
      </header>
      <div className="rw-grid-scroll" role="region" aria-label="Tablo içeriği" tabIndex={0}>
        <table className="rw-grid">
          <thead>
            <tr><th className="rw-corner" scope="col"><span className="rw-sr">Satır</span></th>
              {Array.from({ length: columns }, (_, i) => <th key={i} scope="col" className="rw-colno">Sütun {i + 1}</th>)}</tr>
            {header && grid.rows[0] && <tr><th className="rw-rowno" scope="row">1</th>
              {grid.rows[0].map((slot, i) => slot.covered ? null : <th key={i} scope="col" className="rw-headcell" rowSpan={slot.cell.row_span} colSpan={slot.cell.col_span}>
                <CellView slot={slot} row={0} col={i} /></th>)}</tr>}
          </thead>
          <tbody>
            {grid.rows.map((row, r) => header && r === 0 ? null : <tr key={r}>
              <th className="rw-rowno" scope="row">{r + 1}</th>
              {row.map((slot, i) => slot.covered ? null : <td key={i} rowSpan={slot.cell.row_span} colSpan={slot.cell.col_span}><CellView slot={slot} row={r} col={i} /></td>)}
            </tr>)}
          </tbody>
        </table>
      </div>
      <p className="rw-note" aria-live="polite">{selectedField && selectedState ? <>
        <strong>{selectedField.label}</strong> · <AccessChip editable={selectedState.editable} reason={selectedState.reason} /></> :
        "Bir hücre seçtiğinizde kaynak konumu solda gösterilir. Birleşik hücreler tek hücre olarak görünür; formüllü hücreler düzenlenemez."}</p>
      {grid.loose.length > 0 && <details className="rw-loose">
        <summary>Hücre listesi · tablo ızgarasıyla eşleştirilemedi ({grid.loose.length})</summary>
        <p className="rw-note">Bu tablodaki hücreler ızgaraya güvenle yerleştirilemedi; ızgara salt okunur gösteriliyor. Değerleri aşağıdan düzenleyebilirsiniz.</p>
        <ul className="rw-loose-list">{grid.loose.map((field) => <LooseField key={field.field_id} field={field} />)}</ul>
      </details>}
    </section>
  </div>;
}
function LooseField({ field }: { field: ReviewField }) {
  const c = useCtx();
  const st = fieldState(c, field);
  if (!st) return null;
  return <li className={st.changed ? "is-changed" : ""}>
    <label><span>{field.label}</span>
      {st.editable ? <ScalarInput field={field} label={field.label} onFocus={() => c.select({ nodeId: field.node_id, fieldId: field.field_id })} />
        : <span className="rw-prose">{formatScalar(field.value)} <AccessChip editable={false} reason={st.reason} /></span>}
    </label>
    {st.changed && <Original value={field.value} />}
    {st.error && <p className="rw-error" role="alert">{st.error}</p>}
  </li>;
}

function ArtifactImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return failed ? <div className="rw-img-missing">Görsel dosyası yüklenemedi.</div>
    : <img className="rw-asset-img" src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />;
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
  return <div className="rw-visuals">
    <p className="rw-note rw-note-strong">Dosya türü ve boyutu gibi bilgiler yalnızca dosyayı tanımlar. Bir görselin anlamı, açıklama yazılıp kaynakla kontrol edilene kadar bilinmiyor sayılır.</p>
    {undetected > 0 && <div className="rw-callout">{undetected} görsel kaynakta tespit edildi ancak dosyası çıkarılamadığı için burada önizlenemiyor{coverage ? ` (toplam ${coverage} görsel)` : ""}.</div>}
    {!assets.length ? <Empty title={q ? "Eşleşen görsel yok" : "Görsel yok"} detail={q ? "Aramanızı değiştirin." : "Bu içerikte görsel veya grafik kaydı bulunmuyor."} />
      : <div className="rw-asset-grid">{assets.map(({ node }) => {
        const artifact = snapshot.artifacts.find((item) => item.id === node.artifact_id);
        const field = c.fieldsByNode.get(node.id)?.find((f) => f.kind === "description") ?? null;
        const st = fieldState(c, field);
        const description = field ? (typeof (c.drafts[field.field_id] ?? toRaw(field.value)) === "boolean" ? "" : String(c.drafts[field.field_id] ?? toRaw(field.value))) : node.description ?? "";
        const uncertainties = storedVisualUncertainties(snapshot, node.id);
        const uncertaintyText = field ? c.uncertaintyDrafts[field.field_id] ?? uncertainties.join("\n") : uncertainties.join("\n");
        const notesChanged = uncertaintyText !== uncertainties.join("\n");
        const target: Selection = { nodeId: node.id, fieldId: field?.field_id };
        return <article key={node.id} id={`rw-node-${node.id}`} className={`rw-asset${c.selection?.nodeId === node.id ? " is-selected" : ""}${st?.changed ? " is-changed" : ""}`}
          onClick={() => c.select(target)}>
          <div className="rw-asset-media">
            {artifact && artifact.mime_type.startsWith("image/") ?
              <ArtifactImage src={`${API}/v1/knowledge/revisions/${encodeURIComponent(snapshot.knowledge_revision.id)}/artifacts/${encodeURIComponent(artifact.id)}`}
                alt={node.caption || node.description || "Belgeden çıkarılan görsel"} />
              : <div className="rw-img-missing">{artifact ? "Bu dosya türü önizlenemiyor." : "Bu görsel için dosya çıkarılamadı."}</div>}
          </div>
          <div className="rw-asset-body">
            <span className="rw-kicker">{node.kind === "chart" ? "Grafik" : "Görsel"}</span>
            <h3>{description.trim() ? node.caption || description.split(".")[0] : "Açıklama yok — ekle"}</h3>
            {developerMode && artifact && <p className="rw-meta">Dosya bilgisi: {artifact.mime_type} · {artifact.byte_size.toLocaleString("tr-TR")} bayt. Bu bilgi görselin anlamını doğrulamaz.</p>}
            <div className="rw-block-meta">{st ? <AccessChip editable={st.editable} reason={st.reason} /> : <span className="rw-chip rw-chip-lock">Salt okunur · açıklama alanı yok</span>}
              {(st?.changed || notesChanged) && <span className="rw-chip rw-chip-draft">Taslakta değişti</span>}</div>
            {st?.editable && field ? <ScalarInput field={field} label={`${field.label} (görsel açıklaması)`} multiline onFocus={() => c.select(target)} />
              : <p className="rw-prose">{description ? <Highlight text={description} query={c.query} /> : <span className="rw-unknown">Anlamı bilinmiyor · açıklama yok</span>}</p>}
            {st?.changed && field && <Original value={field.value} />}
            {st?.error && <p className="rw-error" role="alert">{st.error}</p>}
            {uncertainties.length > 0 && <div className="rw-note rw-note-warn"><strong>Görselde belirsiz kalan bilgiler</strong><ul>{uncertainties.map((item, i) => <li key={i}>{item}</li>)}</ul></div>}
            {st?.editable && field && <details><summary>Belirsizlik notlarını düzenle</summary>
              <label><span className="rw-note">Her satır bir not (en fazla 20). Yalnız kaynakta doğruladığınız belirsizlikleri kaldırın.</span>
                <textarea className="rw-textarea" aria-label="Görsel belirsizlik notları" rows={3} value={uncertaintyText} disabled={c.locked}
                  onChange={(e) => c.setUncertaintyDraft(field, e.target.value)} onFocus={() => c.select(target)} /></label>
            </details>}
            <div className="rw-block-actions">
              <button type="button" className="rw-link" onClick={(e) => { e.stopPropagation(); c.select(target, true); }}>Kaynakta göster</button>
              {(st?.changed || notesChanged) && field && <button type="button" className="rw-link rw-link-warn" disabled={c.locked} onClick={(e) => { e.stopPropagation(); c.revert(field); }}>Geri al</button>}
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
  return <div className="rw-gaps">
    <p className="rw-note rw-note-strong">Bu liste kayıtlı eksikleri gösterir. Listenin boş olması, kaynaktaki bütün anlamın doğru çıkarıldığı anlamına gelmez.</p>
    {!gaps.length ? <Empty title="Kayıtlı eksik yok" detail="Sistem bu içerik için eksik kaydı üretmedi; yine de içeriği kaynakla karşılaştırın." /> :
      <ul className="rw-gap-list">{gaps.map((gap) => <li key={gap.key} className="rw-gap">
        <div><strong>{developerMode || gap.nodeId ? gap.title : "İnceleme gerekiyor"}{gap.count > 1 ? ` · ${gap.count} kayıt` : ""}</strong>{gap.detail && <p>{developerMode || gap.nodeId ? gap.detail : "Bu bölümdeki bilgileri özgün dosyayla karşılaştırın."}</p>}</div>
        {gap.nodeId && <button type="button" className="rw-btn" onClick={() => c.openSection("visuals", gap.nodeId)}>Öğeye git</button>}
      </li>)}</ul>}
  </div>;
}

function HistoryPanel({ ws, numbers, displayed, locked, onView }: {
  ws: Workspace; numbers: Map<string, number>; displayed: string; locked: boolean; onView: (id: string) => void;
}) {
  const entries = [...ws.history].sort((a, b) => (numbers.get(b.revision_id) ?? 0) - (numbers.get(a.revision_id) ?? 0));
  return <div className="rw-history">
    <p className="rw-note rw-note-strong"><b>Düzenleme geçmişi</b> bu belgenin içeriğinde yapılan incelemeleri gösterir. Dosya sürümleri yüklenen dosyanın geçmişini gösterir; bir düzenleme kaydetmek kaynak dosyayı değiştirmez.
      Eski düzenlemeler yalnızca görüntülenir; geri yükleme veya onaylama burada yoktur.</p>
    <ol className="rw-history-list">{entries.map((entry) => {
      const isLatest = entry.revision_id === ws.latest_revision_id, shown = entry.revision_id === displayed;
      return <li key={entry.revision_id} className={`rw-rev${shown ? " is-shown" : ""}`}>
        <div className="rw-rev-head">
          <strong>Düzenleme {numbers.get(entry.revision_id)}</strong>
          {isLatest && <span className="rw-chip rw-chip-edit">Güncel</span>}
          {entry.revision_id === ws.approved_revision_id && <span className="rw-chip rw-chip-ok">Onaylı sürüm</span>}
          {shown && <span className="rw-chip rw-chip-draft">Görüntüleniyor</span>}
        </div>
        <p className="rw-meta">{entry.kind === "manual_review" ? "Manuel inceleme" : "İlk çıkarım"} · {dateText(entry.created_at)}</p>
        <p className="rw-meta">İnceleyen: {entry.reviewer_id || "kayıtlı değil"}</p>
        {entry.reason && <p className="rw-prose">{entry.reason}</p>}
        {!shown && <button type="button" className="rw-btn" disabled={locked} onClick={() => onView(entry.revision_id)}>
          {isLatest ? "Güncel içeriği göster" : "Bu içeriği görüntüle"}</button>}
      </li>;
    })}</ol>
  </div>;
}

function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="rw-empty"><strong>{title}</strong><p>{detail}</p></div>;
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
  return <aside className="rw-source" ref={panelRef} aria-label="Kaynak belge">
    <header className="rw-source-head">
      <span className="rw-kicker">Kaynak</span>
      <h2>{ws.source.filename}</h2>
      <a className="rw-btn" href={absolute(ws.source.download_url)} download>Orijinali indir</a>
    </header>
    {evidences.length > 0 && <div className="rw-evidence-chips" role="group" aria-label="Seçili içeriğin kaynak konumları">
      {evidences.map((e) => <button type="button" key={e.id} aria-pressed={e.id === active?.id} onClick={() => setActiveId(e.id)}>{locatorLabel(e.locator)}</button>)}
    </div>}
    {!hasSelection && <p className="rw-note">Sağdaki bir metne, hücreye veya görsele tıklayın; kaynaktaki konumu burada görünür.</p>}
    {hasSelection && evidences.length === 0 && <p className="rw-note rw-note-warn">Seçili içerik için kaynak konumu kaydedilmemiş.</p>}
    {pages.length > 0 && current ? <div className="rw-pager-wrap">
      <div className="rw-pager">
        <button type="button" className="rw-btn" disabled={index === 0} onClick={() => setPage(pages[index - 1].page_number)}>← Önceki</button>
        <span aria-live="polite">Sayfa {current.page_number} / {pages.length}</span>
        <button type="button" className="rw-btn" disabled={index >= pages.length - 1} onClick={() => setPage(pages[index + 1].page_number)}>Sonraki →</button>
      </div>
      {failed === current.render_url ? <div className="rw-img-missing">Sayfa görüntüsü yüklenemedi. Orijinali indirerek kontrol edin.</div> :
        <div className="rw-page">
          <img src={absolute(current.render_url)} alt={`Kaynak belge, sayfa ${current.page_number}`} onError={() => setFailed(current.render_url)} />
          {boxes.map((e) => <span key={e.id} className={`rw-bbox${e.id === active?.id ? " is-active" : ""}`} aria-hidden style={{
            left: `${e.locator.bbox!.x * 100}%`, top: `${e.locator.bbox!.y * 100}%`,
            width: `${e.locator.bbox!.width * 100}%`, height: `${e.locator.bbox!.height * 100}%`,
          }} />)}
        </div>}
      {active?.locator.kind === "pdf_page" && !active.locator.bbox && <p className="rw-note">Bu kayıt için sayfadaki bölge bilinmiyor; yalnızca sayfa gösteriliyor.</p>}
    </div> : active?.locator.kind === "image_region" ? null :
      <div className="rw-nopages">
        <strong>{active ? locatorLabel(active.locator) : "Konum seçilmedi"}</strong>
        <p>Bu kaynak biçimi için sayfa görüntüsü üretilmiyor. Konumu orijinal dosyada açarak kontrol edin; yukarıdaki bağlantı doğrulanmış özgün dosyayı indirir.</p>
      </div>}
    {active && (developerMode || active.locator.kind === "image_region") && <details className="rw-trace" open={active.locator.kind === "image_region"}>
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
    return <div className="rw-wrap"><Empty title="Örnek belgelerde inceleme kapalı" detail="Örnek belgeler gösterilir; belge içeriği üretilmez ve değişiklik kaydedilemez. Bağlantı kurulduğunda burada kaynak ve içerik yan yana görünür." /></div>;
  }
  if (mode === null) return <div className="rw-wrap"><Empty title="Bağlanıyor…" detail="Çalışma modu doğrulandığında belge incelemesi açılır." /></div>;
  if (!ws || !index || !ctx) {
    return <div className="rw-wrap" aria-busy={load.status === "loading"}>
      {load.status === "error" ? <div role="alert"><Empty title="İnceleme açılamadı" detail={developerMode ? load.message : "Belge içeriği alınamadı. Bir süre sonra tekrar deneyin."} />
        <button type="button" className="rw-btn" onClick={() => setReloadTick((t) => t + 1)}>Tekrar dene</button></div>
        : <div className="rw-skeleton" role="status"><span /><span /><span /><p>Belge ve kaynak yükleniyor…</p></div>}
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
    <div className="rw" aria-busy={load.status === "loading"}>
      <header className="rw-top">
        <div className="rw-title">
          <span className="rw-kicker">Belgeyi incele</span>
          <h2>{ws.source.filename}</h2>
          <p>Düzenleme {revNumber ?? "—"}{currentEntry ? ` · ${dateText(currentEntry.created_at)}` : ""}
            {viewLatest ? <span className="rw-chip rw-chip-edit">Güncel</span> : <span className="rw-chip rw-chip-lock">Eski düzenleme · salt okunur</span>}</p>
        </div>
        {view !== "history" && <label className="rw-search"><span className="rw-sr">Belgede ara</span>
          <input type="search" value={query} placeholder="Metin, hücre veya açıklama ara…" onChange={(e) => setQuery(e.target.value)} /></label>}
        {view !== "history" && <nav className="rw-nav" aria-label="Belge bölümleri">
          <div role="tablist" aria-label="Bölümler" onKeyDown={(e) => {
            if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
            const at = sections.findIndex(([key]) => key === section);
            const next = sections[(at + (e.key === "ArrowRight" ? 1 : sections.length - 1)) % sections.length][0];
            setSection(next); document.getElementById(tabId(next))?.focus();
          }}>
            {sections.map(([key, label]) => <button type="button" role="tab" key={key} id={tabId(key)} aria-selected={section === key}
              aria-controls={`${baseId}-panel`} tabIndex={section === key ? 0 : -1} onClick={() => setSection(key)}>
              {label}{key !== "chat" && <i>{counts[key]}</i>}</button>)}
          </div>
        </nav>}
      </header>

      {!viewLatest && <div className="rw-banner rw-banner-warn" role="status">Eski bir düzenlemeyi görüntülüyorsunuz; düzenleme kapalı.
        <button type="button" className="rw-btn" onClick={() => goToRevision(ws.latest_revision_id)} disabled={locked}>Güncel içeriğe dön</button></div>}
      {viewLatest && !ws.can_edit && <div className="rw-banner" role="status">Bu belge şu an düzenlemeye kapalı; içerik yalnızca okunabilir.</div>}
      {load.status === "error" && <div className="rw-banner rw-banner-warn" role="alert">{developerMode ? load.message : "Belge içeriği alınamadı. Tekrar deneyin."}
        <button type="button" className="rw-btn" onClick={() => setReloadTick((t) => t + 1)}>Tekrar dene</button></div>}
      {save.status === "saved" && <div className="rw-banner rw-banner-ok" role="status">{save.message}</div>}
      {view !== "history" && <p className="rw-lede">İçeriği özgün dosyayla karşılaştırın. Değişikliklerinizi gözden geçirip kaydedin; her kayıt düzenleme geçmişine eklenir.</p>}

      {view !== "history" && <button type="button" className="rw-source-toggle" aria-expanded={sourceOpen} onClick={() => setSourceOpen(!sourceOpen)}>
        {sourceOpen ? "Kaynağı gizle" : "Kaynağı göster"}</button>}
      <div className={`rw-body${sourceOpen && view !== "history" ? "" : " is-source-hidden"}`}>
        {sourceOpen && view !== "history" && <SourcePanel ws={ws} evidences={selectedEvidence} activeId={activeEvidenceItem?.id ?? null} setActiveId={setActiveEvidence}
          page={page} setPage={setPage} hasSelection={!!selection} panelRef={sourceRef} />}
        <div className="rw-content" id={`${baseId}-panel`} role="tabpanel" aria-label={view === "history" ? "Düzenleme geçmişi" : undefined} aria-labelledby={view === "history" ? undefined : tabId(section)}>
          {activeSection === "text" && <TextPanel blocks={index.blocks} />}
          {activeSection === "tables" && <TablesPanel blocks={index.blocks} tableId={tableId} setTableId={setTableId} grids={index.grids} />}
          {activeSection === "visuals" && <VisualsPanel blocks={index.blocks} snapshot={ws.snapshot} />}
          {activeSection === "gaps" && <GapsPanel gaps={index.gaps} />}
          {activeSection === "chat" && <RevisionChat snapshot={ws.snapshot} snapshotSha256={ws.snapshot_sha256} versionId={ws.source.document_version_id ?? undefined} revisionLabel={revNumber ? String(revNumber) : undefined} mode={mode} />}
          {activeSection === "history" && <HistoryPanel ws={ws} numbers={index.numbers} displayed={displayedRevision} locked={locked} onView={goToRevision} />}
        </div>
      </div>

      {(dirtyCount > 0 || conflict) && <section className="rw-commit" aria-label="Taslak değişiklikler">
        {commitOpen && <div className="rw-commit-panel" id={`${baseId}-commit`}>
          {conflict && <div className="rw-banner rw-banner-warn" role="alert"><p>{developerMode ? conflict : "Belge siz düzenlerken değişmiş olabilir. Taslağı indirin ve güncel içeriği yükleyin."}</p>
            <div className="rw-row">
              <button type="button" className="rw-btn" onClick={downloadDraft}>Taslağı indir</button>
              <button type="button" className="rw-btn rw-btn-warn" onClick={loadCurrent} disabled={saving}>Güncel içeriği yükle (taslak silinir)</button>
            </div></div>}
          <div className="rw-form">
            <label>İnceleyen kişi<input value={reviewer} autoComplete="off" disabled={locked}
              onChange={(e) => { invalidatePreview(); setReviewer(e.target.value); }} /></label>
            <label>Değişiklik nedeni<textarea value={reason} rows={2} disabled={locked}
              onChange={(e) => { invalidatePreview(); setReason(e.target.value); }} /></label>
          </div>
          <div className="rw-row">
            <button type="button" className="rw-btn rw-btn-primary" disabled={!canSubmit || preview.status === "loading" || locked} onClick={() => void runPreview()}>
              {preview.status === "loading" ? "Önizleniyor…" : "Farkları önizle"}</button>
            <span className="rw-note">{!viewLatest || !ws.can_edit ? "Bu görünümde kayıt yapılamaz." : evaluated.invalid.length ? "Geçersiz değerleri düzeltin." :
              !reviewer.trim() || !reason.trim() ? "Önizleme için inceleyen kişi ve neden gerekli." : "Önizleme hiçbir şeyi kaydetmez."}</span>
          </div>
          {preview.status === "error" && <p className="rw-error" role="alert">{developerMode ? preview.message : "Önizleme alınamadı. Bilgileri kontrol edip tekrar deneyin."}</p>}
          {preview.status === "ready" && <div className="rw-diff">
            <h3>Kaydedilecek farklar</h3>
            {preview.data.warnings.map((warning, i) => <p key={i} className="rw-note rw-note-warn">{developerMode ? warning : "Kaydetmeden önce bu değişikliği özgün dosyayla kontrol edin."}</p>)}
            <ul>{preview.data.changes.map((change) => <li key={change.field_id}>
              <div className="rw-diff-head"><strong>{change.label}</strong><span className="rw-chip">{KIND_LABEL[change.kind]}</span></div>
              <div className="rw-diff-cols">
                <div className="rw-before"><span>Önce</span><p>{formatScalar(change.before)}</p></div>
                <div className="rw-after"><span>Sonra</span><p>{formatScalar(change.after)}</p></div>
              </div>
              {change.visual_uncertainties != null && <div className="rw-diff-cols">
                <div className="rw-before"><span>Önce · belirsizlikler</span><p>{storedVisualUncertainties(ws.snapshot, change.node_id).join("\n") || "Not yok"}</p></div>
                <div className="rw-after"><span>Sonra · belirsizlikler</span><p>{change.visual_uncertainties.join("\n") || "Not yok"}</p></div>
              </div>}
              <div className="rw-block-actions">
                <button type="button" className="rw-link" onClick={() => selectContent({ nodeId: change.node_id, fieldId: change.field_id }, true)}>Kaynakta göster</button>
                <button type="button" className="rw-link" onClick={() => { selectContent({ nodeId: change.node_id, fieldId: change.field_id }); openSection(KIND_SECTION[change.kind], change.node_id); }}>İçerikte göster</button>
              </div>
            </li>)}</ul>
            <label className="rw-check rw-confirm"><input type="checkbox" checked={sourceChecked} disabled={locked} onChange={(e) => setSourceChecked(e.target.checked)} />
              Bu değişiklikleri özgün kaynakla karşılaştırdım. Bu onay yalnızca değiştirilen alanlar içindir; belgenin tamamının doğruluğunu onaylamaz.</label>
            <button type="button" className="rw-btn rw-btn-primary" disabled={!sourceChecked || locked} onClick={() => void runSave()}>
              {saving ? "Kaydediliyor…" : "Değişiklikleri kaydet"}</button>
          </div>}
          {save.status === "error" && <p className="rw-error" role="alert">{developerMode ? save.message : "Değişiklikler kaydedilemedi. Tekrar deneyin."}</p>}
        </div>}
        <div className="rw-commit-bar">
          <strong aria-live="polite">{evaluated.changes.length} değişiklik taslakta{evaluated.invalid.length ? ` · ${evaluated.invalid.length} geçersiz değer` : ""}</strong>
          <span className="rw-note">Henüz kaydedilmedi</span>
          <div className="rw-row">
            <button type="button" className="rw-btn" onClick={downloadDraft}>Taslağı indir</button>
            <button type="button" className="rw-btn" onClick={revertAll} disabled={locked}>Tümünü geri al</button>
            <button type="button" className="rw-btn rw-btn-primary" aria-expanded={commitOpen} aria-controls={`${baseId}-commit`} onClick={() => setCommitOpen(!commitOpen)}>
              {commitOpen ? "Kayıt adımlarını gizle" : "Gözden geçir ve kaydet"}</button>
          </div>
        </div>
      </section>}
    </div>
  </RwContext.Provider>;
}
