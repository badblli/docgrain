"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableRow, TableCell } from "@/components/ui/table";
import { cn } from "@/lib/utils";


import { useDeveloperMode } from "../developer-mode";

import { useMemo, useState } from "react";
import { VisualReview } from "./visual-review";


const inspectorShell = "pt-6 pb-12 flex flex-col min-w-0 [&_>_details]:border [&_>_details]:border-solid [&_>_details]:border-line [&_>_details]:rounded-sm [&_>_details]:bg-paper [&_>_details]:min-w-0 [&_>_details_summary]:cursor-pointer [&_>_details_summary]:font-normal [&_>_details_summary]:text-xs [&_>_details_summary]:font-mono max-[760px]:pt-4 max-[760px]:pb-8 px-8 gap-4 max-[760px]:px-4 [&_>_details_summary]:p-3";
const inspectorHeading = "flex items-end justify-between [&_h2]:mt-1 [&_h2]:mb-0 [&_h2]:font-semibold [&_h2]:text-2xl [&_h2]:font-sans [&_>_span]:text-muted [&_>_span]:font-normal [&_>_span]:text-2xs [&_>_span]:font-mono gap-3 [&_h2]:mx-0";
const inspectorSplit = "min-h-165 grid grid-cols-[minmax(300px,_42%)_minmax(0,1fr)] border border-solid border-line rounded-card overflow-hidden bg-paper max-[1050px]:grid-cols-[minmax(250px,38%)_minmax(0,1fr)] max-[760px]:grid-cols-[1fr]";
const inspectorListPanel = "border-r border-solid border-r-line min-w-0 max-h-[78vh] overflow-auto bg-sheet max-[760px]:max-h-95 max-[760px]:border-r-0 max-[760px]:border-b max-[760px]:border-solid max-[760px]:border-b-line";
const inspectorDetailPanel = "min-w-0 max-h-[78vh] overflow-auto [&_h4]:mt-5 [&_h4]:mb-2 [&_h4]:font-semibold [&_h4]:text-xs [&_h4]:font-sans max-[760px]:max-h-[none] [&_h4]:mx-0 p-5 max-[760px]:p-4";

export type Box = { x: number; y: number; width: number; height: number };
export type Locator =
  | { kind: "pdf_page"; page_number: number; bbox: Box | null }
  | { kind: "image_region"; width_px: number; height_px: number; exif_orientation: number; bbox: Box }
  | { kind: "docx_block"; part: string; path: string }
  | { kind: "text_span"; start: number; end: number }
  | { kind: "spreadsheet_range"; sheet: string; a1_range: string }
  | { kind: "artifact_object"; artifact_id: string; object_path: string | null };
export type Evidence = { id: string; source_version_id: string; locator: Locator; note: string | null };
export type Provenance = {
  method: string; derivation: string; producer_id: string; evidence_ids: string[];
  confidence: number | null; confidence_method: string | null;
};
export type Annotation = { provenance: Provenance; review_status: string };
export type Cell = {
  value: unknown; annotation: Annotation | null; formula: string | null;
  cached_value: unknown; display_text: string | null; row_span: number; col_span: number;
  source_attributes?: Record<string, unknown>;
};
export type Node = {
  id: string; identity_key: string; kind: string; annotation: Annotation;
  field_annotations: Record<string, Annotation>; children?: string[]; title?: string | null;
  heading?: string; level?: number; text?: string; role?: string; rows?: Cell[][];
  caption?: string | null; artifact_id?: string | null; description?: string | null;
  ordered?: boolean;
  source_data?: Record<string, unknown>;
};
export type Issue = {
  code?: string; stage?: string; impact?: string; reason?: string; item_ref?: string;
  location?: unknown; source_format?: string; severity?: string;
};
export type Snapshot = {
  schema_version: string; identity_policy_version: string; document_id: string; workspace_id: string;
  source_version: {
    id: string; filename: string; mime_type: string; byte_size: number; content_sha256: string;
    storage_uri: string; storage_version: string | null; recorded_at: string;
  };
  knowledge_revision: {
    id: string; created_at: string; coverage: string | null; parent_revision_id: string | null;
    producers: { id: string; name: string; version: string | null }[];
  };
  root_node_id: string; structure: Node[]; evidence: Evidence[];
  artifacts: { id: string; role: string; storage_uri: string; mime_type: string; byte_size: number; content_sha256: string }[];
  metadata: {
    structural_parse?: {
      parser?: string; parser_version?: string; source_format?: string;
      coverage?: { status?: string; expected_areas?: string[]; processed_areas?: string[];
        skipped_areas?: string[]; item_counts?: Record<string, number> };
      issues?: Issue[];
    };
  };
};
export type Knowledge = {
  document_id: string; latest_revision_id: string | null; approved_revision_id: string | null;
  snapshot: Snapshot;
};
export type CanonicalTab = "overview" | "structure" | "tables" | "assets" | "issues" | "provenance" | "raw";
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const kindLabel: Record<string, string> = {
  document: "Document", section: "Section", text_block: "TextBlock", list: "List",
  table: "Table", asset: "Asset", chart: "Chart",
};
const stringValue = (value: unknown) => value == null ? "—" : typeof value === "string" ? value : JSON.stringify(value);
const short = (value: string, size = 88) => value.length > size ? `${value.slice(0, size)}…` : value;
const nodeTitle = (node: Node) => node.title || node.heading || node.caption || node.description ||
  (node.kind === "table" ? `${node.rows?.length ?? 0} × ${Math.max(0, ...(node.rows ?? []).map((row) => row.length))}` :
    node.text || node.artifact_id || node.kind);
const nodeEvidence = (node: Node) => Array.from(new Set([
  ...node.annotation.provenance.evidence_ids,
  ...Object.values(node.field_annotations).flatMap((item) => item.provenance.evidence_ids),
  ...(node.rows ?? []).flatMap((row) => row.flatMap((cell) => cell.annotation?.provenance.evidence_ids ?? [])),
]));
const locatorText = (locator: Locator) => {
  switch (locator.kind) {
    case "pdf_page": return `PDF · sayfa ${locator.page_number}${locator.bbox ? " · bbox" : " · bbox yok"}`;
    case "image_region": return `Görsel · ${locator.width_px} × ${locator.height_px} px · kaynak bbox`;
    case "docx_block": return `DOCX · ${locator.part} · ${locator.path}`;
    case "text_span": return `TXT · [${locator.start}, ${locator.end})`;
    case "spreadsheet_range": return `XLSX · ${locator.sheet}!${locator.a1_range}`;
    case "artifact_object": return `Artifact · ${locator.artifact_id}${locator.object_path ? ` · ${locator.object_path}` : ""}`;
  }
};
const dateText = (value: string) => new Date(value).toLocaleString("tr-TR");

function displayedImageBox(box: Box, orientation: number): Box {
  const point = (x: number, y: number): [number, number] => {
    switch (orientation) {
      case 2: return [1-x, y]; case 3: return [1-x, 1-y]; case 4: return [x, 1-y];
      case 5: return [y, x]; case 6: return [1-y, x]; case 7: return [1-y, 1-x]; case 8: return [y, 1-x];
      default: return [x, y];
    }
  };
  const corners = [point(box.x, box.y), point(box.x+box.width, box.y),
    point(box.x, box.y+box.height), point(box.x+box.width, box.y+box.height)];
  const x = Math.min(...corners.map(([x]) => x)), y = Math.min(...corners.map(([, y]) => y));
  return { x, y, width: Math.max(...corners.map(([x]) => x))-x, height: Math.max(...corners.map(([, y]) => y))-y };
}

function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="border border-dashed border-line rounded-lg bg-paper text-ink2 [&_strong]:font-semibold [&_strong]:text-md [&_strong]:font-sans [&_p]:mt-1 [&_p]:mb-0 [&_p]:text-muted [&_p]:text-xs py-10 px-6 [&_p]:mx-0"><strong>{title}</strong><p>{detail}</p></div>;
}
function Field({ label, value }: { label: string; value: unknown }) {
  return <div className="contents [&_dt]:border-b [&_dt]:border-solid [&_dt]:border-b-line2 [&_dt]:min-w-0 [&_dd]:border-b [&_dd]:border-solid [&_dd]:border-b-line2 [&_dd]:min-w-0 [&_dt]:text-muted [&_dt]:text-2xs [&_dd]:font-normal [&_dd]:text-2xs [&_dd]:leading-[1.55] [&_dd]:font-mono [&_dd]:wrap-anywhere [&_dd]:text-ink [&_dt]:py-2 [&_dt]:px-0 [&_dd]:py-2 [&_dd]:px-0 [&_dt]:m-0 [&_dd]:m-0"><dt>{label}</dt><dd>{stringValue(value)}</dd></div>;
}
function EvidenceLinks({ ids, snapshot, onSelect }: {
  ids: string[]; snapshot: Snapshot; onSelect: (id: string) => void;
}) {
  if (!ids.length) return <p className="text-muted text-xs leading-[1.55]">Evidence reference yok.</p>;
  return <div className="flex flex-wrap gap-2">{ids.map((id) => {
    const evidence = snapshot.evidence.find((item) => item.id === id);
    return <Button variant="ghost" className="h-auto whitespace-normal border border-solid border-accent-line bg-accent-soft rounded-sm text-left flex flex-col max-w-full [&_span]:text-accent [&_span]:text-2xs [&_small]:font-normal [&_small]:text-2xs [&_small]:font-mono [&_small]:text-faint [&_small]:wrap-anywhere [&:hover]:bg-accent-soft p-2" key={id} onClick={() => onSelect(id)}>
      <span>{evidence ? locatorText(evidence.locator) : id}</span><small>{id}</small>
    </Button>;
  })}</div>;
}

export function EvidenceView({ evidence, snapshot, versionId }: {
  evidence: Evidence; snapshot: Snapshot; versionId?: string;
}) {
  const developerMode = useDeveloperMode();
  const locator = evidence.locator;
  const linked = snapshot.structure.filter((node) => nodeEvidence(node).includes(evidence.id));
  const provenance = linked.flatMap((node) => [
    node.annotation.provenance,
    ...Object.values(node.field_annotations).map((item) => item.provenance),
    ...(node.rows ?? []).flatMap((row) => row.flatMap((cell) => cell.annotation ? [cell.annotation.provenance] : [])),
  ]).filter((item) => item.evidence_ids.includes(evidence.id));
  const producerIds = Array.from(new Set(provenance.map((item) => item.producer_id)));
  const methods = Array.from(new Set(provenance.map((item) => item.method)));
  const derivations = Array.from(new Set(provenance.map((item) => item.derivation)));
  const sourceImage = snapshot.artifacts.find((item) => item.content_sha256 === snapshot.source_version.content_sha256);
  const imageBox = locator.kind === "image_region" ? displayedImageBox(locator.bbox, locator.exif_orientation) : null;
  return <div className="mt-4 mb-0 border-t border-solid border-t-line pt-4 mx-0">
    <div className="mb-4 [&_h3]:font-semibold [&_h3]:text-md [&_h3]:leading-[1.22] [&_h3]:font-sans [&_h3]:mt-1 [&_h3]:mb-2 [&_h3]:wrap-anywhere [&_h3]:mx-0"><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">{developerMode ? "SOURCE TRACE" : "Kaynak"}</span><h3>{developerMode ? locatorText(locator) : "Kaynak görseli"}</h3></div>
    {developerMode && <dl className="grid grid-cols-[minmax(100px,150px)_minmax(0,1fr)] gap-y-0 gap-x-4 m-0">
      <Field label="Evidence ID" value={evidence.id} />
      <Field label="Source version" value={evidence.source_version_id} />
      <Field label="Locator" value={locator.kind} />
      {locator.kind === "pdf_page" && <><Field label="Page" value={locator.page_number} />
        <Field label="BBox" value={locator.bbox ? JSON.stringify(locator.bbox) : "Unavailable"} /></>}
      {locator.kind === "image_region" && <><Field label="Özgün piksel boyutu" value={`${locator.width_px} × ${locator.height_px}`} />
        <Field label="EXIF orientation" value={locator.exif_orientation} /><Field label="Özgün piksel çerçevesi / bbox" value={JSON.stringify(locator.bbox)} /></>}
      {locator.kind === "docx_block" && <><Field label="Part" value={locator.part} /><Field label="Path" value={locator.path} /></>}
      {locator.kind === "text_span" && <Field label="Unicode span" value={`[${locator.start}, ${locator.end})`} />}
      {locator.kind === "spreadsheet_range" && <><Field label="Sheet" value={locator.sheet} /><Field label="A1 range" value={locator.a1_range} /></>}
      {locator.kind === "artifact_object" && <Field label="Object path" value={locator.object_path} />}
      <Field label="Linked nodes" value={linked.length} />
      <Field label="Linked node IDs" value={linked.map((node) => node.id).join(", ") || "—"} />
      <Field label="Linked methods" value={methods.join(", ") || "—"} />
      <Field label="Linked derivations" value={derivations.join(", ") || "—"} />
      <Field label="Producer refs" value={producerIds.join(", ") || "—"} />
      {provenance.some((item) => item.confidence_method?.startsWith("easyocr")) && <Field label="OCR · kaynak doğrulaması bekliyor"
        value={provenance.map((item) => `${item.confidence_method ?? "native"} · ${item.confidence ?? "—"}`).join(", ")} />}
      {evidence.note && <Field label="Note" value={evidence.note} />}
    </dl>}
    {locator.kind === "image_region" && <div className="mt-4">
      {sourceImage && imageBox ? <div className="relative w-[min(100%,520px)] leading-0 border border-solid border-line shadow-none [&_img]:w-full [&_img]:h-auto [&_img]:block">
        <img src={`${API_BASE}/v1/knowledge/revisions/${snapshot.knowledge_revision.id}/artifacts/${sourceImage.id}`} alt="Özgün kaynak görseli" />
        <div className="absolute border-[2px] border-solid border-warn bg-warn-soft [box-shadow:0_0_0_1px_var(--warn-line)] pointer-events-none" aria-label="Görseldeki kaynak konumu" style={{
          left: `${imageBox.x * 100}%`, top: `${imageBox.y * 100}%`, width: `${imageBox.width * 100}%`, height: `${imageBox.height * 100}%`,
        }} />
      </div> : <Empty title="Kaynak görseli yok" detail="Özgün görsel dosyası bulunamadı." />}
      <p className="text-muted text-xs leading-[1.55]">Çerçeve, özgün görseldeki kaynak konumunu gösterir.</p>
    </div>}
    {locator.kind === "pdf_page" && <div className="mt-4">
      {versionId ? <div className="relative w-[min(100%,520px)] leading-0 border border-solid border-line shadow-none [&_img]:w-full [&_img]:h-auto [&_img]:block">
        <img src={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/v1/versions/${versionId}/pages/${locator.page_number}/render`}
          alt={`Kaynak PDF sayfa ${locator.page_number}`} />
        {locator.bbox && <div className="absolute border-[2px] border-solid border-warn bg-warn-soft [box-shadow:0_0_0_1px_var(--warn-line)] pointer-events-none" aria-label="Sayfadaki kaynak konumu" style={{
          left: `${locator.bbox.x * 100}%`, top: `${locator.bbox.y * 100}%`,
          width: `${locator.bbox.width * 100}%`, height: `${locator.bbox.height * 100}%`,
        }} />}
      </div> : <Empty title="Sayfa görüntüsü yok" detail="Bu kaynak için PDF dosya sürümü bulunamadı." />}
      <p className="text-muted text-xs leading-[1.55]">{locator.bbox ? "Sarı çerçeve, bilginin kaynak sayfadaki konumunu gösterir." : "Sayfadaki konum belirlenemedi; kaynak sayfa yine de gösterilir."}</p>
    </div>}
  </div>;
}

function NodeDetail({ node, parent, snapshot, versionId }: {
  node: Node; parent?: Node; snapshot: Snapshot; versionId?: string;
}) {
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null);
  const [rawOpen, setRawOpen] = useState(false);
  const evidenceIds = nodeEvidence(node);
  const active = snapshot.evidence.find((item) => item.id === selectedEvidence) ??
    snapshot.evidence.find((item) => item.id === evidenceIds[0]);
  const provenance = node.annotation.provenance;
  return <div className="[&_h4]:mt-5 [&_h4]:mb-2 [&_h4]:font-semibold [&_h4]:text-xs [&_h4]:font-sans [&_h4]:mx-0">
    <div className="mb-4 [&_h3]:font-semibold [&_h3]:text-xl [&_h3]:leading-[1.22] [&_h3]:font-sans [&_h3]:mt-1 [&_h3]:mb-2 [&_h3]:wrap-anywhere [&_h3]:mx-0"><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">NODE INSPECTOR</span>
      <h3>{short(nodeTitle(node), 110)}</h3><Badge variant="secondary" className="rounded-xs font-mono text-2xs">{kindLabel[node.kind] ?? node.kind}</Badge></div>
    <dl className="grid grid-cols-[minmax(100px,150px)_minmax(0,1fr)] gap-y-0 gap-x-4 m-0">
      <Field label="Node ID" value={node.id} /><Field label="Identity key" value={node.identity_key} />
      <Field label="Parent" value={parent?.id} /><Field label="Children" value={node.children?.length} />
      {node.role && <Field label="Role" value={node.role} />}
      {node.level && <Field label="Heading level" value={node.level} />}
      {node.text && <Field label="Text" value={node.text} />}
      {node.rows && <Field label="Dimensions" value={`${node.rows.length} × ${Math.max(0, ...node.rows.map((row) => row.length))}`} />}
      {node.artifact_id && <Field label="Artifact ID" value={node.artifact_id} />}
      <Field label="Method" value={provenance.method} /><Field label="Derivation" value={provenance.derivation} />
      <Field label="Producer" value={provenance.producer_id} /><Field label="Review" value={node.annotation.review_status} />
      <Field label="Evidence refs" value={evidenceIds.length} />
    </dl>
    <h4>Evidence & provenance</h4>
    <EvidenceLinks ids={evidenceIds} snapshot={snapshot} onSelect={setSelectedEvidence} />
    {active && <EvidenceView key={active.id} evidence={active} snapshot={snapshot} versionId={versionId} />}
    <Button variant="ghost" className="h-auto whitespace-normal border-0 bg-transparent text-accent font-bold text-2xs font-mono py-3 px-0" onClick={() => setRawOpen(!rawOpen)} aria-expanded={rawOpen}>Raw node {rawOpen ? "−" : "+"}</Button>
    {rawOpen && <pre className="bg-sunken text-ink2 rounded-lg whitespace-pre-wrap wrap-anywhere overflow-auto max-h-[650px] font-normal text-2xs leading-[1.6] font-mono p-4">{JSON.stringify(node, null, 2)}</pre>}
  </div>;
}

export function Overview({ knowledge, status }: { knowledge: Knowledge; status: string }) {
  const snapshot = knowledge.snapshot;
  const parse = snapshot.metadata.structural_parse;
  const coverage = parse?.coverage;
  const issues = parse?.issues ?? [];
  const counts = snapshot.structure.reduce<Record<string, number>>((acc, node) => {
    acc[node.kind] = (acc[node.kind] ?? 0) + 1;
    return acc;
  }, {});
  const issueGroups = Object.entries(issues.reduce<Record<string, number>>((acc, issue) => {
    const reason = issue.reason || issue.code || "Unknown issue";
    acc[reason] = (acc[reason] ?? 0) + 1;
    return acc;
  }, {}));
  const metrics: [string, number][] = [
    ["Structural nodes", snapshot.structure.length], ["Sections", counts.section ?? 0],
    ["Text blocks", counts.text_block ?? 0], ["List nodes", counts.list ?? 0],
    ["Tables", counts.table ?? 0], ["Pictures detected", coverage?.item_counts?.picture ?? 0],
    ["Paragraphs", coverage?.item_counts?.paragraph ?? 0], ["List items", coverage?.item_counts?.list_item ?? 0],
    ["Evidence", snapshot.evidence.length], ["Issues", issues.length],
  ];
  return <div className={inspectorShell}>
    <section className="min-h-45 flex items-end justify-between text-ink bg-paper border border-solid border-line rounded-card [background-image:none] [&_h2]:font-semibold [&_h2]:text-[clamp(var(--text-lg),_2.5vw,_var(--text-2xl))] [&_h2]:leading-[1.13] [&_h2]:font-sans [&_h2]:mt-3 [&_h2]:mb-2 [&_h2]:max-w-180 [&_h2]:wrap-anywhere [&_p]:text-muted [&_p]:font-normal [&_p]:text-2xs [&_p]:font-mono max-[760px]:items-start max-[760px]:flex-col py-6 px-8 gap-6 [&_h2]:mx-0 [&_p]:m-0"><div><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">CANONICAL KNOWLEDGE · {snapshot.schema_version}</span>
      <h2>{snapshot.source_version.filename}</h2><p>Document → Source → Processing → Canonical Knowledge</p></div>
      <div className="flex flex-col items-end text-right whitespace-nowrap [&_strong]:text-warn [&_strong]:font-bold [&_strong]:text-base [&_strong]:font-mono [&_strong]:uppercase [&_strong]:tracking-[.09em] [&_span]:text-muted [&_span]:font-normal [&_span]:text-2xs [&_span]:font-mono [&_span]:mt-2 max-[760px]:items-start max-[760px]:text-left"><strong>{coverage?.status ?? snapshot.knowledge_revision.coverage ?? status}</strong>
        <span>{coverage?.processed_areas?.length ?? "—"} / {coverage?.expected_areas?.length ?? "—"} areas processed</span></div></section>
    <div className="grid grid-cols-[repeat(4,minmax(0,1fr))] border border-solid border-line rounded-card overflow-hidden bg-line max-[1050px]:grid-cols-[repeat(2,1fr)] max-[760px]:grid-cols-[repeat(2,1fr)] gap-1">{metrics.map(([label, value]) => <div className="bg-paper flex flex-col [&_strong]:font-semibold [&_strong]:text-xl [&_strong]:leading-[1.1] [&_strong]:font-sans [&_strong]:text-ink [&_span]:text-muted [&_span]:font-normal [&_span]:text-2xs [&_span]:font-mono [&_span]:uppercase [&_span]:tracking-[.03em] gap-1 p-4" key={label}>
      <strong>{value}</strong><span>{label}</span></div>)}</div>
    {issueGroups.length > 0 && <div className="border border-solid border-warn-line border-l-[4px] border-l-warn rounded-lg bg-warn-soft [&_strong]:text-warn [&_strong]:text-xs [&_p]:mt-1 [&_p]:mb-0 [&_p]:text-xs [&_p]:text-warn py-3 px-4 [&_p]:mx-0"><strong>Partial coverage · {issues.length} issue</strong>
      {issueGroups.map(([reason, count]) => <p key={reason}>{count} × {reason}</p>)}</div>}
    <div className="grid grid-cols-[repeat(2,minmax(0,1fr))] max-[760px]:grid-cols-[1fr] gap-4"><section className="bg-paper border border-solid border-line rounded-card min-w-0 [&_h3]:mt-0 [&_h3]:mb-4 [&_h3]:font-semibold [&_h3]:text-lg [&_h3]:font-sans [&_h3]:mx-0 p-4"><h3>Revision</h3><dl className="grid grid-cols-[minmax(100px,150px)_minmax(0,1fr)] gap-y-0 gap-x-4 m-0">
      <Field label="Revision ID" value={snapshot.knowledge_revision.id} />
      <Field label="Latest head" value={knowledge.latest_revision_id} />
      <Field label="Approved head" value={knowledge.approved_revision_id} />
      <Field label="Created" value={dateText(snapshot.knowledge_revision.created_at)} />
      <Field label="Schema" value={snapshot.schema_version} />
      <Field label="Parser" value={`${parse?.parser ?? "—"} ${parse?.parser_version ?? ""}`} />
      <Field label="Producers" value={snapshot.knowledge_revision.producers.map((p) => `${p.name}${p.version ? ` ${p.version}` : ""}`).join(", ")} />
      <Field label="Item counts" value={coverage?.item_counts ? Object.entries(coverage.item_counts).map(([k, v]) => `${k}: ${v}`).join(" · ") : "—"} />
    </dl></section><section className="bg-paper border border-solid border-line rounded-card min-w-0 [&_h3]:mt-0 [&_h3]:mb-4 [&_h3]:font-semibold [&_h3]:text-lg [&_h3]:font-sans [&_h3]:mx-0 p-4"><h3>Source integrity</h3><dl className="grid grid-cols-[minmax(100px,150px)_minmax(0,1fr)] gap-y-0 gap-x-4 m-0">
      <Field label="Source ID" value={snapshot.source_version.id} />
      <Field label="Filename" value={snapshot.source_version.filename} />
      <Field label="MIME / format" value={`${snapshot.source_version.mime_type} · ${parse?.source_format ?? "—"}`} />
      <Field label="Byte size" value={snapshot.source_version.byte_size.toLocaleString("tr-TR")} />
      <Field label="SHA-256 · verified at ingestion" value={snapshot.source_version.content_sha256} />
      <Field label="Storage version" value={snapshot.source_version.storage_version} />
      <Field label="Recorded" value={dateText(snapshot.source_version.recorded_at)} />
    </dl></section></div>
  </div>;
}

export function Structure({ snapshot, versionId }: { snapshot: Snapshot; versionId?: string }) {
  const nodes = useMemo(() => new Map(snapshot.structure.map((node) => [node.id, node])), [snapshot]);
  const parents = useMemo(() => new Map(snapshot.structure.flatMap((node) => (node.children ?? []).map((id) => [id, node.id] as const))), [snapshot]);
  const [selected, setSelected] = useState(snapshot.root_node_id);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([snapshot.root_node_id, snapshot.structure.find((n) => n.kind === "section")?.id ?? ""]));
  const [query, setQuery] = useState("");
  const matching = useMemo(() => {
    if (!query.trim()) return null;
    const matches = new Set<string>();
    for (const node of snapshot.structure) {
      if (`${nodeTitle(node)} ${node.id} ${node.kind}`.toLocaleLowerCase("tr-TR").includes(query.trim().toLocaleLowerCase("tr-TR"))) {
        let id: string | undefined = node.id;
        while (id) { matches.add(id); id = parents.get(id); }
      }
    }
    return matches;
  }, [query, snapshot, parents]);
  const renderNode = (id: string, depth: number): React.ReactNode => {
    const node = nodes.get(id);
    if (!node || (matching && !matching.has(id))) return null;
    const children = node.children ?? [];
    const open = matching ? true : expanded.has(id);
    return <div key={id} className="">
      <div className={cn(`flex items-center min-h-[35px] pr-2 border-l-[3px] border-solid border-l-transparent [&:hover]:bg-accent-soft ${selected === id ? "bg-accent-soft border-l-accent" : ""}`)} style={{ paddingLeft: `${12 + depth * 17}px` }}>
        {children.length > 0 ? <Button variant="ghost" className="h-auto whitespace-normal border-0 bg-transparent w-5 h-6 text-lg leading-[18px] text-muted flex-none p-0" aria-label={`${open ? "Kapat" : "Aç"} ${nodeTitle(node)}`}
          aria-expanded={open} onClick={() => setExpanded((previous) => {
            const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next;
          })}>{open ? "⌄" : "›"}</Button> : <span className="w-5 flex-none" />}
        <Button variant="ghost" className="h-auto whitespace-normal flex-1 min-w-0 flex items-center border-0 bg-transparent text-left gap-2 py-1 px-0" aria-current={selected === id} onClick={() => setSelected(id)}>
          <Badge variant="secondary" className="rounded-xs font-mono text-2xs">{kindLabel[node.kind] ?? node.kind}</Badge>
          <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-2xs" title={nodeTitle(node)}>{short(nodeTitle(node))}</span>
        </Button>
      </div>
      {open && children.map((child) => renderNode(child, depth + 1))}
    </div>;
  };
  const current = nodes.get(selected) ?? nodes.get(snapshot.root_node_id);
  return <div className={inspectorShell}><div className={inspectorHeading}><div><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">CANONICAL STRUCTURE</span><h2>Reading order</h2></div><span>{snapshot.structure.length} nodes</span></div>
    <div className={inspectorSplit}><section className={inspectorListPanel}><label className="flex flex-col font-bold text-2xs font-mono text-muted tracking-[.05em] uppercase border-b border-solid border-b-line2 [&_input]:w-full [&_input]:font-normal [&_input]:text-xs [&_input]:font-sans [&_input]:border [&_input]:border-solid [&_input]:border-line [&_input]:rounded-sm [&_input]:[outline:none] [&_input]:bg-paper [&_input:focus]:border-accent [&_input:focus]:[box-shadow:0_0_0_2px_var(--accent-line)] gap-1 [&_input]:py-2 [&_input]:px-3 p-3">Node ara
      <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Başlık, tür veya ID…" /></label>
      <div className="py-2 px-0" role="tree">{renderNode(snapshot.root_node_id, 0)}</div>
      {matching && matching.size === 0 && <Empty title="Eşleşme yok" detail="Başka bir başlık veya node ID deneyin." />}
    </section><section className={inspectorDetailPanel}>{current && <NodeDetail key={current.id} node={current} parent={nodes.get(parents.get(current.id) ?? "")} snapshot={snapshot} versionId={versionId} />}</section></div>
  </div>;
}

export function Tables({ snapshot, versionId }: { snapshot: Snapshot; versionId?: string }) {
  const tables = snapshot.structure.filter((node) => node.kind === "table");
  const nodes = new Map(snapshot.structure.map((node) => [node.id, node]));
  const parents = new Map(snapshot.structure.flatMap((node) => (node.children ?? []).map((id) => [id, node.id] as const)));
  const [selected, setSelected] = useState(tables[0]?.id ?? "");
  const current = tables.find((node) => node.id === selected);
  const evidence = current ? nodeEvidence(current).map((id) => snapshot.evidence.find((item) => item.id === id)).filter((item): item is Evidence => !!item) : [];
  return <div className={inspectorShell}><div className={inspectorHeading}><div><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">CANONICAL TABLES</span><h2>Tables</h2></div><span>{tables.length} table nodes</span></div>
    {!tables.length ? <Empty title="Tablo yok" detail="Bu revision’da canonical TableNode bulunmuyor." /> :
      <div className={inspectorSplit}><div className={inspectorListPanel}>{tables.map((table, index) => {
        const refs = nodeEvidence(table).map((id) => snapshot.evidence.find((e) => e.id === id)).filter((e): e is Evidence => !!e);
        const section = nodes.get(parents.get(table.id) ?? "");
        return <Button variant="ghost" key={table.id} className={cn(`[&:hover]:bg-accent-soft w-full border-0 border-b border-solid border-b-line2 border-l-[3px] border-l-transparent bg-transparent flex flex-col text-left [&_strong]:font-semibold [&_strong]:text-sm [&_strong]:leading-[1.35] [&_strong]:font-sans [&_small]:text-muted [&_small]:font-normal [&_small]:text-2xs [&_small]:leading-[1.45] [&_small]:font-mono [&_small]:wrap-anywhere py-3 px-4 gap-1 ${table.id === selected ? "bg-accent-soft border-l-accent" : ""}`)} onClick={() => setSelected(table.id)}>
          <span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">TABLE {String(index + 1).padStart(2, "0")}</span><strong>{short(nodeTitle(table))}</strong>
          {section?.heading && <small>Section · {section.heading}</small>}
          <small>{table.rows?.length ?? 0} rows × {Math.max(0, ...(table.rows ?? []).map((r) => r.length))} columns · {refs.length} evidence</small>
          <small>{refs.map((e) => locatorText(e.locator)).join(" · ")}</small>
        </Button>;
      })}</div><div className={inspectorDetailPanel}>{current && <>
        <div className="mb-4 [&_h3]:font-semibold [&_h3]:text-xl [&_h3]:leading-[1.22] [&_h3]:font-sans [&_h3]:mt-1 [&_h3]:mb-2 [&_h3]:wrap-anywhere [&_h3]:mx-0"><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">TABLE INSPECTOR</span><h3>{nodeTitle(current)}</h3></div>
        <dl className="grid grid-cols-[minmax(100px,150px)_minmax(0,1fr)] gap-y-0 gap-x-4 m-0"><Field label="Node ID" value={current.id} /><Field label="Rows" value={current.rows?.length} />
          <Field label="Columns" value={Math.max(0, ...(current.rows ?? []).map((r) => r.length))} />
          <Field label="Evidence refs" value={evidence.length} /></dl>
        <div className="max-w-full overflow-auto mt-4 border border-solid border-line rounded-sm"><Table containerClassName="overflow-visible" className="[&_td]:whitespace-normal border-collapse font-normal text-2xs leading-[1.45] font-sans w-full [&_td]:border [&_td]:border-solid [&_td]:border-line [&_td]:min-w-[90px] [&_td]:align-[top] [&_tr:nth-child(even)]:bg-sheet [&_td_small]:block [&_td_small]:text-faint [&_td_small]:font-normal [&_td_small]:text-2xs [&_td_small]:font-mono [&_td_small]:mt-1 [&_td]:p-2"><TableBody>{current.rows?.map((row, rowIndex) => <TableRow key={rowIndex}>
          {row.map((cell, cellIndex) => cell.source_attributes?.merge_covered ? null : <TableCell key={cellIndex} rowSpan={cell.row_span} colSpan={cell.col_span}>
            <span>{cell.display_text ?? stringValue(cell.value)}</span>
            {cell.formula && <small>Formula: {cell.formula}</small>}
            {cell.cached_value != null && <small>Cached: {stringValue(cell.cached_value)}</small>}
            {cell.source_attributes?.number_format != null && <small>Sayı biçimi: {String(cell.source_attributes.number_format)}</small>}
          </TableCell>)}</TableRow>)}</TableBody></Table></div>
        <h4>Source evidence</h4>{evidence.map((item) => <EvidenceView key={item.id} evidence={item} snapshot={snapshot} versionId={versionId} />)}
        {evidence.length === 0 && <p className="text-muted text-xs leading-[1.55]">Bu tablonun evidence referansı yok.</p>}
      </>}</div></div>}
  </div>;
}

export function Assets({ snapshot, versionId }: { snapshot: Snapshot; versionId?: string }) {
  const assets = snapshot.structure.filter((node) => node.kind === "asset" || node.kind === "chart");
  const parse = snapshot.metadata.structural_parse;
  const pictureIssues = (parse?.issues ?? []).filter((issue) => issue.code === "unextracted_picture");
  const pictureCount = parse?.coverage?.item_counts?.picture ?? 0;
  return <div className={inspectorShell}><div className={inspectorHeading}><div><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">CANONICAL ASSETS</span><h2>Detected visuals</h2></div><span>{assets.length} asset nodes · {pictureCount} pictures detected</span></div>
    <VisualReview snapshot={snapshot} />
    {pictureCount > 0 && pictureIssues.length > 0 && <div className="border border-solid border-warn-line border-l-[4px] border-l-warn rounded-lg bg-warn-soft [&_strong]:text-warn [&_strong]:text-xs [&_p]:mt-1 [&_p]:mb-0 [&_p]:text-xs [&_p]:text-warn py-3 px-4 [&_p]:mx-0"><strong>{pictureCount} picture detected · binary extraction unavailable</strong>
      <p>Parser coverage ve structural issue kayıtları bu resimleri bildiriyor. Binary artifact ve AssetNode üretilmediği için önizleme mevcut değil.</p></div>}
    {pictureIssues.length > 0 && <div className="grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-3">{pictureIssues.map((issue, index) => <section className="bg-paper border border-solid border-line rounded-card min-w-0 [&_h3]:font-semibold [&_h3]:text-lg [&_h3]:font-sans [&_h3]:mt-3 [&_h3]:mb-1 [&_p]:text-muted [&_p]:text-2xs [&_code]:text-muted [&_code]:font-normal [&_code]:text-2xs [&_code]:font-mono [&_code]:wrap-anywhere [&_h3]:mx-0 p-4" key={`${issue.item_ref}-${index}`}>
      <span className="inline-flex flex-none rounded-xs font-bold text-2xs font-mono bg-sheet text-muted p-1">Detected picture</span><h3>{issue.item_ref ?? `Picture ${index + 1}`}</h3>
      <p>{issue.reason ?? "Binary extraction unavailable"}</p><code>{issue.stage ?? "structural_parse"}</code>
    </section>)}</div>}
    {!assets.length && !pictureIssues.length ? <Empty title="Asset yok" detail="Bu revision’da canonical AssetNode, ChartNode veya tespit edilmiş picture kaydı bulunmuyor." /> :
      <div className="grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-3">{assets.map((node) => {
        const artifact = snapshot.artifacts.find((item) => item.id === node.artifact_id);
        const refs = nodeEvidence(node).map((id) => snapshot.evidence.find((item) => item.id === id)).filter((item): item is Evidence => !!item);
        return <section className="bg-paper border border-solid border-line rounded-card min-w-0 [&_h3]:font-semibold [&_h3]:text-lg [&_h3]:font-sans [&_h3]:mt-3 [&_h3]:mb-1 [&_p]:text-muted [&_p]:text-2xs [&_code]:text-muted [&_code]:font-normal [&_code]:text-2xs [&_code]:font-mono [&_code]:wrap-anywhere [&_h3]:mx-0 p-4" key={node.id}><Badge variant="secondary" className="rounded-xs font-mono text-2xs">{kindLabel[node.kind]}</Badge>
          <h3>{node.description || node.caption || "Detected picture"}</h3>
          <p>{artifact ? `${artifact.mime_type} · ${artifact.byte_size.toLocaleString("tr-TR")} bytes` : "Binary extraction unavailable"}</p>
          {artifact?.role === "source-image" && <img className="relative w-full leading-0 border border-solid border-line shadow-none [&_img]:w-full [&_img]:h-auto [&_img]:block" src={`${API_BASE}/v1/knowledge/revisions/${encodeURIComponent(snapshot.knowledge_revision.id)}/artifacts/${encodeURIComponent(artifact.id)}`} alt={node.description || node.caption || "Extracted document image"} loading="lazy" />}
          <code>{node.id}</code><p>{refs.map((item) => locatorText(item.locator)).join(" · ") || "Locator unavailable"}</p>
          {refs.map((item) => <EvidenceView key={item.id} evidence={item} snapshot={snapshot} versionId={versionId} />)}
        </section>;
      })}</div>}
  </div>;
}

export function Issues({ snapshot }: { snapshot: Snapshot }) {
  const issues = snapshot.metadata.structural_parse?.issues ?? [];
  const [filter, setFilter] = useState("all");
  const types = Array.from(new Set(issues.map((issue) => issue.code || "unknown")));
  const shown = filter === "all" ? issues : issues.filter((issue) => issue.code === filter);
  return <div className={inspectorShell}><div className={inspectorHeading}><div><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">STRUCTURAL PARSE</span><h2>Issues</h2></div><span>{issues.length} issues</span></div>
    {!issues.length ? <Empty title="Issue yok" detail="Bu revision’ın structural parse metadata kaydında issue bulunmuyor." /> : <>
      <div className="flex flex-wrap [&_button]:border [&_button]:border-solid [&_button]:border-line [&_button]:rounded-sm [&_button]:bg-paper [&_button]:font-normal [&_button]:text-2xs [&_button]:font-mono [&_button[aria-pressed='true']]:bg-accent [&_button[aria-pressed='true']]:text-on-accent [&_button[aria-pressed='true']]:border-accent gap-1 [&_button]:py-2 [&_button]:px-3"><Button variant="ghost" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All · {issues.length}</Button>
        {types.map((type) => <Button variant="ghost" aria-pressed={filter === type} key={type} onClick={() => setFilter(type)}>{type} · {issues.filter((issue) => issue.code === type).length}</Button>)}</div>
      <div className="grid gap-2">{shown.map((issue, index) => <section className="bg-paper border border-solid border-line border-l-[3px] border-l-warn rounded-sm [&_>_div]:flex [&_>_div]:items-center [&_>_div]:mb-2 [&_strong]:text-xs py-3 px-4 [&_>_div]:gap-2" key={`${issue.code}-${issue.item_ref}-${index}`}>
        <div><span className="inline-flex flex-none rounded-xs font-bold text-2xs font-mono bg-sheet text-muted p-1">{issue.code ?? "issue"}</span><strong>{issue.reason || "No reason recorded"}</strong></div>
        <dl className="grid grid-cols-[80px_minmax(0,1fr)] gap-y-0 gap-x-4 m-0"><Field label="Stage" value={issue.stage} /><Field label="Impact" value={issue.impact} />
          <Field label="Format" value={issue.source_format} /><Field label="Item ref" value={issue.item_ref} />
          <Field label="Location" value={issue.location} />{issue.severity && <Field label="Severity" value={issue.severity} />}</dl>
      </section>)}</div></>}
  </div>;
}

export function ProvenanceView({ snapshot, versionId }: { snapshot: Snapshot; versionId?: string }) {
  const [selected, setSelected] = useState(snapshot.evidence.find((item) => item.locator.kind === "pdf_page" && item.locator.bbox)?.id ?? snapshot.evidence[0]?.id ?? "");
  const [query, setQuery] = useState("");
  const visible = snapshot.evidence.filter((item) => `${item.id} ${locatorText(item.locator)}`.toLocaleLowerCase("tr-TR").includes(query.toLocaleLowerCase("tr-TR")));
  const current = snapshot.evidence.find((item) => item.id === selected);
  return <div className={inspectorShell}><div className={inspectorHeading}><div><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">SOURCE TRACE</span><h2>Evidence & provenance</h2></div><span>{snapshot.evidence.length} records</span></div>
    {!snapshot.evidence.length ? <Empty title="Evidence yok" detail="Bu revision’da kaynak evidence kaydı bulunmuyor." /> :
      <div className={inspectorSplit}><div className={inspectorListPanel}><label className="flex flex-col font-bold text-2xs font-mono text-muted tracking-[.05em] uppercase border-b border-solid border-b-line2 [&_input]:w-full [&_input]:font-normal [&_input]:text-xs [&_input]:font-sans [&_input]:border [&_input]:border-solid [&_input]:border-line [&_input]:rounded-sm [&_input]:[outline:none] [&_input]:bg-paper [&_input:focus]:border-accent [&_input:focus]:[box-shadow:0_0_0_2px_var(--accent-line)] gap-1 [&_input]:py-2 [&_input]:px-3 p-3">Evidence ara<Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="ID veya locator…" /></label>
        {visible.map((item) => <Button variant="ghost" key={item.id} className={cn(`[&:hover]:bg-accent-soft w-full border-0 border-b border-solid border-b-line2 border-l-[3px] border-l-transparent bg-transparent flex flex-col text-left [&_strong]:font-semibold [&_strong]:text-sm [&_strong]:leading-[1.35] [&_strong]:font-sans [&_small]:text-muted [&_small]:font-normal [&_small]:text-2xs [&_small]:leading-[1.45] [&_small]:font-mono [&_small]:wrap-anywhere py-3 px-4 gap-1 ${item.id === selected ? "bg-accent-soft border-l-accent" : ""}`)} onClick={() => setSelected(item.id)}>
          <strong>{locatorText(item.locator)}</strong><small>{item.id}</small></Button>)}
        {!visible.length && <Empty title="Eşleşme yok" detail="Başka bir evidence ID veya locator deneyin." />}</div>
      <div className={inspectorDetailPanel}>{current && <EvidenceView evidence={current} snapshot={snapshot} versionId={versionId} />}</div></div>}
  </div>;
}

export function Raw({ snapshot }: { snapshot: Snapshot }) {
  const [copied, setCopied] = useState(false);
  const content = JSON.stringify(snapshot, null, 2);
  return <div className={inspectorShell}><div className={inspectorHeading}><div><span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">DEVELOPER INSPECTION</span><h2>CanonicalKnowledgeSnapshot</h2></div>
    <Button variant="ghost" className="h-auto whitespace-normal border border-solid border-line rounded-sm bg-paper font-normal text-2xs font-mono py-2 px-3" onClick={async () => { await navigator.clipboard.writeText(content); setCopied(true); }}>{copied ? "Copied" : "Copy JSON"}</Button></div>
    <div className="grid [&_details]:border [&_details]:border-solid [&_details]:border-line [&_details]:rounded-sm [&_details]:bg-paper [&_details]:min-w-0 [&_summary]:cursor-pointer [&_summary]:font-normal [&_summary]:text-xs [&_summary]:font-mono [&_summary_span]:text-muted [&_summary_span]:[float:right] gap-1 [&_summary]:p-3">{(["source_version", "knowledge_revision", "structure", "evidence", "artifacts", "metadata"] as const).map((key) =>
      <details key={key}><summary>{key} <span>{Array.isArray(snapshot[key]) ? snapshot[key].length : ""}</span></summary>
        <pre className="bg-sunken text-ink2 rounded-lg whitespace-pre-wrap wrap-anywhere overflow-auto max-h-[650px] font-normal text-2xs leading-[1.6] font-mono mt-0 mb-2 mx-2 p-4">{JSON.stringify(snapshot[key], null, 2)}</pre></details>)}</div>
    <details><summary>Full snapshot JSON</summary><pre className="bg-sunken text-ink2 rounded-lg whitespace-pre-wrap wrap-anywhere overflow-auto max-h-[650px] font-normal text-2xs leading-[1.6] font-mono mt-0 mb-2 mx-2 p-4">{content}</pre></details>
  </div>;
}
