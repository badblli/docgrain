"use client";

import { useEffect, useState } from "react";
import { EvidenceView, type Evidence, type Node, type Snapshot } from "./inspector";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Output = {
  version: string; format: string; canonical_revision_id: string;
  content: Node[]; evidence: Evidence[];
  assets: { artifact: { id: string; mime_type: string }; api_path: string; file: string }[];
  quality: { structural_status: string; semantic_status: string; text_only_complete: boolean;
    measurements: Record<string, number>; gaps: { code: string; detail: string; object_id: string | null }[] };
};
const valueText = (value: unknown) => typeof value === "string" ? value : JSON.stringify(value);
const gapLabels: Record<string, [string, string]> = {
  missing_visual_description: ["Görsel açıklaması eksik", "Resim dosyası korundu; içeriği henüz metne aktarılmadı. OCR veya görsel yorumlama gerekiyor."],
  formula_result_unavailable: ["Formül sonucu mevcut değil", "Formül korundu ancak dosyada hesaplanmış değeri bulunmuyor; sonuç üretilmedi."],
  no_text_or_table_content: ["Metin veya tablo çıkarılamadı", "Kaynak için OCR veya görsel inceleme gerekiyor."],
  structural_coverage_incomplete: ["Kapsam veya kaynak doğrulaması açık", "Çıkarım eksikleri veya doğrulanmamış OCR kayıtları var. Ayrıntıları kaynak belgeyle karşılaştırın."],
  parser_issue: ["Parser çıkarım sorunu", "Kaynakta çıkarım sırasında kaydedilen bir sorun var."],
};
function gapLabel(gap: { code: string; detail: string }): [string, string] {
  if (gap.code === "parser_issue") {
    try {
      const issue = JSON.parse(gap.detail);
      if (issue.code === "ocr_needs_review") return ["OCR metni doğrulanmadı", "Görselden okunan metin korundu. Sayı ve harfleri kaynakla karşılaştırmadan onaylanmış bilgi sayılmaz."];
      if (issue.code === "ocr_low_confidence") return ["OCR okuması belirsiz", "Bazı satırların tanıma puanı düşük. Özgün görseli açıp özellikle sayı ve Türkçe karakterleri kontrol edin."];
      if (issue.code === "no_ocr_text") return ["Görselde metin bulunamadı", "Özgün dosya korundu; boş görsel, fotoğraf, plan veya okunamayan metin olabilir. Görsel anlamı henüz yorumlanmadı."];
    } catch { /* Existing parser issues can be plain text. */ }
  }
  return gapLabels[gap.code] ?? [gap.code, gap.detail];
}

export function AIOutputView({ snapshot, versionId }: { snapshot: Snapshot; versionId?: string }) {
  const revision = snapshot.knowledge_revision.id;
  const [output, setOutput] = useState<Output | null>(null);
  const [message, setMessage] = useState("Ortak çıktı yükleniyor…");
  const [view, setView] = useState("content");
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null);
  const [copyState, setCopyState] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setOutput(null); setMessage("Ortak çıktı yükleniyor…"); setSelectedEvidence(null);
    fetch(`${API}/v1/knowledge/revisions/${encodeURIComponent(revision)}/outputs`, { signal: abort.signal })
      .then(async response => {
        if (!response.ok) throw new Error(response.status === 404 ? "Bu revision için ortak çıktı henüz yayımlanmamış." : `Çıktı okunamadı (${response.status}).`);
        return response.json();
      }).then(data => { if (!abort.signal.aborted) { setOutput(data.output); setMessage(""); } })
      .catch(error => { if (!abort.signal.aborted) setMessage(error.message); });
    return () => abort.abort();
  }, [revision]);
  if (!output) return <div className="ci-wrap"><div className="ci-empty"><strong>AI çıktısı</strong><p>{message}</p></div></div>;
  const base = `${API}/v1/knowledge/revisions/${encodeURIComponent(revision)}`;
  const metrics = output.quality.measurements;
  const evidence = snapshot.evidence.find(e => e.id === selectedEvidence);
  const visualGaps = output.quality.gaps.filter(g => g.code === "missing_visual_description").length;
  return <div className="ci-wrap ai-output">
    <div className="ci-hero"><div><p className="ci-eyebrow">PDF · DOCX · TXT · XLSX · PNG · JPEG → ortak model</p>
      <h2>AI için ortak doküman çıktısı</h2><p>Metin, tablo ve kaynak kanıtları tek JSON biçiminde. Resimler bu paketin dosya ekleridir.</p></div>
      <a className="ci-copy" href={`${base}/package`}>Tüm paketi indir · ZIP</a></div>
    <div className={`ai-readiness ${output.quality.text_only_complete ? "ai-ready" : "ai-review"}`}>
      <strong>{output.quality.text_only_complete ? "Çıkarılan metin ve tablolar ortak biçimde hazır" : "Ortak biçim hazır · içerik için ek işlem gerekiyor"}</strong>
      <p>{visualGaps ? `${visualGaps} görselin dosyası mevcut; anlamı metne aktarılmamış. Metin modeli bu görselleri okuyamaz. ` : ""}
        {output.quality.gaps.length ? `${output.quality.gaps.length} açık içerik/kapsam kaydı var. ` : ""}
        Kaynaktaki bütün anlamın eksiksiz çıkarıldığı henüz doğrulanmış değil.</p>
    </div>
    <div className="ci-metric-grid">{[["Metin karakteri", metrics.text_characters], ["Tablo / hücre", `${metrics.tables} / ${metrics.table_cells}`],
      ["Görsel", metrics.visual_nodes], ["Kaynak kanıtı", metrics.evidence]].map(([label,value]) =>
      <div className="ci-card" key={label}><small>{label}</small><strong className="ai-count">{value}</strong></div>)}</div>
    <div className="ai-downloads"><code>docgrain.ai-document · {output.version}</code>
      {[["ai.json","Ortak JSON"],["canonical.md","Okunabilir metin"],["canonical.json","Canonical JSON"],["chunks.jsonl","Chunks"],["manifest.json","Kapsam / checksum"],["ai.schema.json","JSON Schema"]].map(([name,label]) =>
        <a key={name} href={`${base}/outputs/${name}`}>{label} ↓</a>)}</div>
    <div className="ci-filters ai-tabs">{[["content","İçerik"],["gaps",`Eksikler (${output.quality.gaps.length})`],["json","Ortak JSON"]].map(([key,label]) =>
      <button key={key} aria-pressed={view === key} onClick={() => setView(key)}>{label}</button>)}</div>
    {view === "gaps" && <div className="ci-issue-list">{output.quality.gaps.length ? output.quality.gaps.map((gap,index) =>
      <div className="ci-issue" key={`${gap.object_id}-${index}`}><strong>{gapLabel(gap)[0]}</strong>
        <p>{gapLabel(gap)[1]}</p><details><summary>Kayıt ayrıntısı</summary><code>{gap.code}</code><p>{gap.detail}</p>{gap.object_id && <code>{gap.object_id}</code>}</details></div>) :
      <div className="ci-empty"><strong>Kayıtlı çıkarım eksiği yok</strong><p>Bu durum kaynak belgedeki bütün bilginin bağımsız doğrulaması değildir.</p></div>}</div>}
    {view === "json" && <><button className="ci-copy" onClick={async () => {
      try { await navigator.clipboard.writeText(JSON.stringify(output,null,2)); setCopyState("Kopyalandı"); }
      catch { setCopyState("Kopyalanamadı; JSON dosyasını indirebilirsin."); }
    }}>JSON kopyala</button> <span>{copyState}</span><pre className="ci-json">{JSON.stringify(output,null,2)}</pre></>}
    {view === "content" && <div className="ai-blocks">{output.content.filter(n => n.kind !== "document" && n.kind !== "list").map(node => {
      const asset = output.assets.find(a => a.artifact.id === node.artifact_id);
      const ids = Array.from(new Set([...node.annotation.provenance.evidence_ids,
        ...(node.rows ?? []).flatMap(row => row.flatMap(c => c.annotation?.provenance.evidence_ids ?? []))]));
      return <article className="ai-block" key={node.id}>
        {node.annotation.provenance.confidence_method?.startsWith("easyocr") && <p className="ci-muted">
          {node.annotation.provenance.confidence_method.endsWith(":mixed") ? "Native metin + OCR" : "OCR metni"} · kaynakla doğrulanmadı</p>}
        {node.kind === "section" && <h3>{node.heading}</h3>}
        {node.kind === "text_block" && <p className="ai-text">{node.text}</p>}
        {node.kind === "table" && <><h3>{node.caption || "Tablo"} <small>{node.rows?.length} satır</small></h3>
          <div className="ci-table-scroll"><table className="ci-data-table"><tbody>{node.rows?.map((row,r) => <tr key={r}>{row.map((cell,c) =>
            <td key={c}>{cell.value == null ? "∅" : valueText(cell.value)}
              {cell.formula && <small>Formül: {cell.formula} · cached: {valueText(cell.cached_value)}</small>}
              {(cell.row_span > 1 || cell.col_span > 1) && <small>Birleşik hücre: {cell.row_span} × {cell.col_span}</small>}
              {cell.display_text != null && cell.display_text !== valueText(cell.value) && <small>Kaynak gösterimi: {cell.display_text}</small>}
            </td>)}</tr>)}</tbody></table></div></>}
        {(node.kind === "asset" || node.kind === "chart") && <><h3>{node.description || "Görsel içerik"}</h3>
          {asset?.artifact.mime_type.startsWith("image/") && <img className="ai-image" src={`${API}${asset.api_path}`} alt={node.description || "Kaynak belgeden çıkarılan görsel; içerik henüz yorumlanmadı"} loading="lazy" />}
          <p>{node.description || "Görselin anlamı metin çıktısında yok; OCR veya görsel yorumlama gerekiyor."}</p></>}
        {!!ids.length && <details><summary>Kaynak kanıtları · {ids.length}</summary><div className="ci-evidence-links">{ids.map(id =>
          <button className="ci-evidence-link" key={id} onClick={() => setSelectedEvidence(id)}>{id}</button>)}</div></details>}
        {evidence && ids.includes(evidence.id) && <EvidenceView evidence={evidence} snapshot={snapshot} versionId={versionId} />}
      </article>;
    })}</div>}
  </div>;
}
