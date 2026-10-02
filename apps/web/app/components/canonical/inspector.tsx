"use client";

import { useMemo, useState } from "react";

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
};
export type Node = {
  id: string; identity_key: string; kind: string; annotation: Annotation;
  field_annotations: Record<string, Annotation>; children?: string[]; title?: string | null;
  heading?: string; level?: number; text?: string; role?: string; rows?: Cell[][];
  caption?: string | null; artifact_id?: string | null; description?: string | null;
  ordered?: boolean;
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
  return <div className="ci-empty"><strong>{title}</strong><p>{detail}</p></div>;
}
function Field({ label, value }: { label: string; value: unknown }) {
  return <div className="ci-field"><dt>{label}</dt><dd>{stringValue(value)}</dd></div>;
}
function EvidenceLinks({ ids, snapshot, onSelect }: {
  ids: string[]; snapshot: Snapshot; onSelect: (id: string) => void;
}) {
  if (!ids.length) return <p className="ci-muted">Evidence reference yok.</p>;
  return <div className="ci-evidence-links">{ids.map((id) => {
    const evidence = snapshot.evidence.find((item) => item.id === id);
    return <button className="ci-evidence-link" key={id} onClick={() => onSelect(id)}>
      <span>{evidence ? locatorText(evidence.locator) : id}</span><small>{id}</small>
    </button>;
  })}</div>;
}

export function EvidenceView({ evidence, snapshot, versionId }: {
  evidence: Evidence; snapshot: Snapshot; versionId?: string;
}) {
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
  return <div className="ci-evidence-detail">
    <div className="ci-panel-title"><span className="ci-kicker">SOURCE TRACE</span><h3>{locatorText(locator)}</h3></div>
    <dl className="ci-fields">
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
    </dl>
    {locator.kind === "image_region" && <div className="ci-render">
      {sourceImage && imageBox ? <div className="ci-page-image">
        <img src={`${API_BASE}/v1/knowledge/revisions/${snapshot.knowledge_revision.id}/artifacts/${sourceImage.id}`} alt="Özgün kaynak görseli" />
        <div className="ci-bbox" aria-label="Original image bounding box" style={{
          left: `${imageBox.x * 100}%`, top: `${imageBox.y * 100}%`, width: `${imageBox.width * 100}%`, height: `${imageBox.height * 100}%`,
        }} />
      </div> : <Empty title="Kaynak görseli yok" detail="Özgün binary artifact bulunamadı." />}
      <p className="ci-muted">Çerçeve özgün görseldeki kaynak konumudur; görüntüleme sırasında EXIF yönü uygulanır.</p>
    </div>}
    {locator.kind === "pdf_page" && <div className="ci-render">
      {versionId ? <div className="ci-page-image">
        <img src={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/v1/versions/${versionId}/pages/${locator.page_number}/render`}
          alt={`Kaynak PDF sayfa ${locator.page_number}`} />
        {locator.bbox && <div className="ci-bbox" aria-label="Normalized PDF bounding box" style={{
          left: `${locator.bbox.x * 100}%`, top: `${locator.bbox.y * 100}%`,
          width: `${locator.bbox.width * 100}%`, height: `${locator.bbox.height * 100}%`,
        }} />}
      </div> : <Empty title="Page render unavailable" detail="Bu kaynak için PDF version kaydı yok." />}
      <p className="ci-muted">{locator.bbox ? "Sarı çerçeve, kaynak sayfadaki normalized top-left bbox konumunu gösterir." : "BBox unavailable · kaynak sayfa yine de gösterilir."}</p>
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
  return <div className="ci-node-detail">
    <div className="ci-panel-title"><span className="ci-kicker">NODE INSPECTOR</span>
      <h3>{short(nodeTitle(node), 110)}</h3><span className={`ci-kind ci-kind-${node.kind}`}>{kindLabel[node.kind] ?? node.kind}</span></div>
    <dl className="ci-fields">
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
    <button className="ci-text-button" onClick={() => setRawOpen(!rawOpen)} aria-expanded={rawOpen}>Raw node {rawOpen ? "−" : "+"}</button>
    {rawOpen && <pre className="ci-json">{JSON.stringify(node, null, 2)}</pre>}
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
  return <div className="ci-wrap">
    <section className="ci-hero"><div><span className="ci-kicker">CANONICAL KNOWLEDGE · {snapshot.schema_version}</span>
      <h2>{snapshot.source_version.filename}</h2><p>Document → Source → Processing → Canonical Knowledge</p></div>
      <div className="ci-hero-status"><strong>{coverage?.status ?? snapshot.knowledge_revision.coverage ?? status}</strong>
        <span>{coverage?.processed_areas?.length ?? "—"} / {coverage?.expected_areas?.length ?? "—"} areas processed</span></div></section>
    <div className="ci-metric-grid">{metrics.map(([label, value]) => <div className="ci-metric" key={label}>
      <strong>{value}</strong><span>{label}</span></div>)}</div>
    {issueGroups.length > 0 && <div className="ci-callout"><strong>Partial coverage · {issues.length} issue</strong>
      {issueGroups.map(([reason, count]) => <p key={reason}>{count} × {reason}</p>)}</div>}
    <div className="ci-two-col"><section className="ci-card"><h3>Revision</h3><dl className="ci-fields">
      <Field label="Revision ID" value={snapshot.knowledge_revision.id} />
      <Field label="Latest head" value={knowledge.latest_revision_id} />
      <Field label="Approved head" value={knowledge.approved_revision_id} />
      <Field label="Created" value={dateText(snapshot.knowledge_revision.created_at)} />
      <Field label="Schema" value={snapshot.schema_version} />
      <Field label="Parser" value={`${parse?.parser ?? "—"} ${parse?.parser_version ?? ""}`} />
      <Field label="Producers" value={snapshot.knowledge_revision.producers.map((p) => `${p.name}${p.version ? ` ${p.version}` : ""}`).join(", ")} />
      <Field label="Item counts" value={coverage?.item_counts ? Object.entries(coverage.item_counts).map(([k, v]) => `${k}: ${v}`).join(" · ") : "—"} />
    </dl></section><section className="ci-card"><h3>Source integrity</h3><dl className="ci-fields">
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
    return <div key={id} className="ci-tree-branch">
      <div className={`ci-tree-row ${selected === id ? "selected" : ""}`} style={{ paddingLeft: `${12 + depth * 17}px` }}>
        {children.length > 0 ? <button className="ci-disclose" aria-label={`${open ? "Kapat" : "Aç"} ${nodeTitle(node)}`}
          aria-expanded={open} onClick={() => setExpanded((previous) => {
            const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next;
          })}>{open ? "⌄" : "›"}</button> : <span className="ci-disclose-placeholder" />}
        <button className="ci-tree-select" aria-current={selected === id} onClick={() => setSelected(id)}>
          <span className={`ci-kind ci-kind-${node.kind}`}>{kindLabel[node.kind] ?? node.kind}</span>
          <span className="ci-tree-title" title={nodeTitle(node)}>{short(nodeTitle(node))}</span>
        </button>
      </div>
      {open && children.map((child) => renderNode(child, depth + 1))}
    </div>;
  };
  const current = nodes.get(selected) ?? nodes.get(snapshot.root_node_id);
  return <div className="ci-wrap"><div className="ci-section-heading"><div><span className="ci-kicker">CANONICAL STRUCTURE</span><h2>Reading order</h2></div><span>{snapshot.structure.length} nodes</span></div>
    <div className="ci-split"><section className="ci-tree-panel"><label className="ci-search-label">Node ara
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Başlık, tür veya ID…" /></label>
      <div className="ci-tree-scroll" role="tree">{renderNode(snapshot.root_node_id, 0)}</div>
      {matching && matching.size === 0 && <Empty title="Eşleşme yok" detail="Başka bir başlık veya node ID deneyin." />}
    </section><section className="ci-inspector-panel">{current && <NodeDetail key={current.id} node={current} parent={nodes.get(parents.get(current.id) ?? "")} snapshot={snapshot} versionId={versionId} />}</section></div>
  </div>;
}

export function Tables({ snapshot, versionId }: { snapshot: Snapshot; versionId?: string }) {
  const tables = snapshot.structure.filter((node) => node.kind === "table");
  const nodes = new Map(snapshot.structure.map((node) => [node.id, node]));
  const parents = new Map(snapshot.structure.flatMap((node) => (node.children ?? []).map((id) => [id, node.id] as const)));
  const [selected, setSelected] = useState(tables[0]?.id ?? "");
  const current = tables.find((node) => node.id === selected);
  const evidence = current ? nodeEvidence(current).map((id) => snapshot.evidence.find((item) => item.id === id)).filter((item): item is Evidence => !!item) : [];
  return <div className="ci-wrap"><div className="ci-section-heading"><div><span className="ci-kicker">CANONICAL TABLES</span><h2>Tables</h2></div><span>{tables.length} table nodes</span></div>
    {!tables.length ? <Empty title="Tablo yok" detail="Bu revision’da canonical TableNode bulunmuyor." /> :
      <div className="ci-split"><div className="ci-list-panel">{tables.map((table, index) => {
        const refs = nodeEvidence(table).map((id) => snapshot.evidence.find((e) => e.id === id)).filter((e): e is Evidence => !!e);
        const section = nodes.get(parents.get(table.id) ?? "");
        return <button key={table.id} className={`ci-list-item ${table.id === selected ? "selected" : ""}`} onClick={() => setSelected(table.id)}>
          <span className="ci-kicker">TABLE {String(index + 1).padStart(2, "0")}</span><strong>{short(nodeTitle(table))}</strong>
          {section?.heading && <small>Section · {section.heading}</small>}
          <small>{table.rows?.length ?? 0} rows × {Math.max(0, ...(table.rows ?? []).map((r) => r.length))} columns · {refs.length} evidence</small>
          <small>{refs.map((e) => locatorText(e.locator)).join(" · ")}</small>
        </button>;
      })}</div><div className="ci-inspector-panel">{current && <>
        <div className="ci-panel-title"><span className="ci-kicker">TABLE INSPECTOR</span><h3>{nodeTitle(current)}</h3></div>
        <dl className="ci-fields"><Field label="Node ID" value={current.id} /><Field label="Rows" value={current.rows?.length} />
          <Field label="Columns" value={Math.max(0, ...(current.rows ?? []).map((r) => r.length))} />
          <Field label="Evidence refs" value={evidence.length} /></dl>
        <div className="ci-table-scroll"><table className="ci-data-table"><tbody>{current.rows?.map((row, rowIndex) => <tr key={rowIndex}>
          {row.map((cell, cellIndex) => <td key={cellIndex} rowSpan={cell.row_span} colSpan={cell.col_span}>
            <span>{cell.display_text ?? stringValue(cell.value)}</span>
            {cell.formula && <small>Formula: {cell.formula}</small>}
            {cell.cached_value != null && <small>Cached: {stringValue(cell.cached_value)}</small>}
          </td>)}</tr>)}</tbody></table></div>
        <h4>Source evidence</h4>{evidence.map((item) => <EvidenceView key={item.id} evidence={item} snapshot={snapshot} versionId={versionId} />)}
        {evidence.length === 0 && <p className="ci-muted">Bu tablonun evidence referansı yok.</p>}
      </>}</div></div>}
  </div>;
}

export function Assets({ snapshot, versionId }: { snapshot: Snapshot; versionId?: string }) {
  const assets = snapshot.structure.filter((node) => node.kind === "asset" || node.kind === "chart");
  const parse = snapshot.metadata.structural_parse;
  const pictureIssues = (parse?.issues ?? []).filter((issue) => issue.code === "unextracted_picture");
  const pictureCount = parse?.coverage?.item_counts?.picture ?? 0;
  return <div className="ci-wrap"><div className="ci-section-heading"><div><span className="ci-kicker">CANONICAL ASSETS</span><h2>Detected visuals</h2></div><span>{assets.length} asset nodes · {pictureCount} pictures detected</span></div>
    {pictureCount > 0 && pictureIssues.length > 0 && <div className="ci-callout"><strong>{pictureCount} picture detected · binary extraction unavailable</strong>
      <p>Parser coverage ve structural issue kayıtları bu resimleri bildiriyor. Binary artifact ve AssetNode üretilmediği için önizleme mevcut değil.</p></div>}
    {pictureIssues.length > 0 && <div className="ci-asset-grid">{pictureIssues.map((issue, index) => <section className="ci-card ci-asset" key={`${issue.item_ref}-${index}`}>
      <span className="ci-kind ci-kind-asset">Detected picture</span><h3>{issue.item_ref ?? `Picture ${index + 1}`}</h3>
      <p>{issue.reason ?? "Binary extraction unavailable"}</p><code>{issue.stage ?? "structural_parse"}</code>
    </section>)}</div>}
    {!assets.length && !pictureIssues.length ? <Empty title="Asset yok" detail="Bu revision’da canonical AssetNode, ChartNode veya tespit edilmiş picture kaydı bulunmuyor." /> :
      <div className="ci-asset-grid">{assets.map((node) => {
        const artifact = snapshot.artifacts.find((item) => item.id === node.artifact_id);
        const refs = nodeEvidence(node).map((id) => snapshot.evidence.find((item) => item.id === id)).filter((item): item is Evidence => !!item);
        return <section className="ci-card ci-asset" key={node.id}><span className={`ci-kind ci-kind-${node.kind}`}>{kindLabel[node.kind]}</span>
          <h3>{node.description || node.caption || "Detected picture"}</h3>
          <p>{artifact ? `${artifact.mime_type} · ${artifact.byte_size.toLocaleString("tr-TR")} bytes` : "Binary extraction unavailable"}</p>
          {artifact?.role === "source-image" && <img className="ci-page-image" src={`${API_BASE}/v1/knowledge/revisions/${encodeURIComponent(snapshot.knowledge_revision.id)}/artifacts/${encodeURIComponent(artifact.id)}`} alt={node.description || node.caption || "Extracted document image"} loading="lazy" />}
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
  return <div className="ci-wrap"><div className="ci-section-heading"><div><span className="ci-kicker">STRUCTURAL PARSE</span><h2>Issues</h2></div><span>{issues.length} issues</span></div>
    {!issues.length ? <Empty title="Issue yok" detail="Bu revision’ın structural parse metadata kaydında issue bulunmuyor." /> : <>
      <div className="ci-filters"><button aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All · {issues.length}</button>
        {types.map((type) => <button aria-pressed={filter === type} key={type} onClick={() => setFilter(type)}>{type} · {issues.filter((issue) => issue.code === type).length}</button>)}</div>
      <div className="ci-issue-list">{shown.map((issue, index) => <section className="ci-issue" key={`${issue.code}-${issue.item_ref}-${index}`}>
        <div><span className="ci-kind ci-kind-asset">{issue.code ?? "issue"}</span><strong>{issue.reason || "No reason recorded"}</strong></div>
        <dl className="ci-fields"><Field label="Stage" value={issue.stage} /><Field label="Impact" value={issue.impact} />
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
  return <div className="ci-wrap"><div className="ci-section-heading"><div><span className="ci-kicker">SOURCE TRACE</span><h2>Evidence & provenance</h2></div><span>{snapshot.evidence.length} records</span></div>
    {!snapshot.evidence.length ? <Empty title="Evidence yok" detail="Bu revision’da kaynak evidence kaydı bulunmuyor." /> :
      <div className="ci-split"><div className="ci-list-panel"><label className="ci-search-label">Evidence ara<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="ID veya locator…" /></label>
        {visible.map((item) => <button key={item.id} className={`ci-list-item ${item.id === selected ? "selected" : ""}`} onClick={() => setSelected(item.id)}>
          <strong>{locatorText(item.locator)}</strong><small>{item.id}</small></button>)}
        {!visible.length && <Empty title="Eşleşme yok" detail="Başka bir evidence ID veya locator deneyin." />}</div>
      <div className="ci-inspector-panel">{current && <EvidenceView evidence={current} snapshot={snapshot} versionId={versionId} />}</div></div>}
  </div>;
}

export function Raw({ snapshot }: { snapshot: Snapshot }) {
  const [copied, setCopied] = useState(false);
  const content = JSON.stringify(snapshot, null, 2);
  return <div className="ci-wrap"><div className="ci-section-heading"><div><span className="ci-kicker">DEVELOPER INSPECTION</span><h2>CanonicalKnowledgeSnapshot</h2></div>
    <button className="ci-copy" onClick={async () => { await navigator.clipboard.writeText(content); setCopied(true); }}>{copied ? "Copied" : "Copy JSON"}</button></div>
    <div className="ci-raw-sections">{(["source_version", "knowledge_revision", "structure", "evidence", "artifacts", "metadata"] as const).map((key) =>
      <details key={key}><summary>{key} <span>{Array.isArray(snapshot[key]) ? snapshot[key].length : ""}</span></summary>
        <pre className="ci-json">{JSON.stringify(snapshot[key], null, 2)}</pre></details>)}</div>
    <details><summary>Full snapshot JSON</summary><pre className="ci-json">{content}</pre></details>
  </div>;
}
