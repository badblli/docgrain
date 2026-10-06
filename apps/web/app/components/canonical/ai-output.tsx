"use client";

import { Button } from "@/components/ui/button";
import { Table, TableBody, TableRow, TableCell } from "@/components/ui/table";
import { cn } from "@/lib/utils";


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
  missing_visual_description: ["Görsel açıklaması eksik", "Görsel veya grafiğin anlamı henüz metne aktarılmadı. Mevcut binary dosyasını ya da kaynak grafik verisini inceleyin."],
  visual_uncertainty: ["Görselde belirsiz bilgi", "Açıklama var ancak görselde bazı bilgiler hâlâ doğrulanamadı; kayıt ayrıntısını ve kaynağı inceleyin."],
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
      if (issue.code === "native_table_reconciled") return ["Tablo kaynak geometrisiyle karşılaştırıldı", "Hücre metni kaynak çizgileriyle eşleştirildi. Parser'ın farklı değeri korundu; değişiklikler kaynakla inceleme gerektiriyor."];
      if (issue.code === "table_grid_conflict") return ["Tablo yapısı çelişiyor", "İki okuyucu satır veya sütun sayısında uyuşmuyor. Tablo otomatik olarak yeniden şekillendirilmedi."];
      if (issue.code === "table_boundary_text_review") return ["Hücre sınırında metin var", "Kırpılmış veya taşan kelimeler ayrıca kaydedildi. Başlığı kaynak PDF ile kontrol edin."];
      if (issue.code === "chart_visual_unverified") return ["Grafik verisi korundu", "Seriler ve kaynak hücreler çıkarıldı. Görsel yerleşim ve yorum henüz doğrulanmadı."];
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
  if (!output) return <div className="pt-6 pb-12 flex flex-col min-w-0 [&_>_details]:border [&_>_details]:border-solid [&_>_details]:border-line [&_>_details]:rounded-sm [&_>_details]:bg-paper [&_>_details]:min-w-0 [&_>_details_summary]:cursor-pointer [&_>_details_summary]:font-normal [&_>_details_summary]:text-xs [&_>_details_summary]:font-mono max-[760px]:pt-4 max-[760px]:pb-8 px-8 gap-4 max-[760px]:px-4 [&_>_details_summary]:p-3"><div className="border border-dashed border-line rounded-lg bg-paper text-ink2 [&_strong]:font-semibold [&_strong]:text-md [&_strong]:font-sans [&_p]:mt-1 [&_p]:mb-0 [&_p]:text-muted [&_p]:text-xs py-10 px-6 [&_p]:mx-0"><strong>AI çıktısı</strong><p>{message}</p></div></div>;
  const base = `${API}/v1/knowledge/revisions/${encodeURIComponent(revision)}`;
  const metrics = output.quality.measurements;
  const evidence = snapshot.evidence.find(e => e.id === selectedEvidence);
  const visualGaps = output.quality.gaps.filter(g => ["missing_visual_description", "visual_uncertainty"].includes(g.code)).length;
  return <div className="pt-6 pb-12 flex flex-col min-w-0 [&_>_details]:border [&_>_details]:border-solid [&_>_details]:border-line [&_>_details]:rounded-sm [&_>_details]:bg-paper [&_>_details]:min-w-0 [&_>_details_summary]:cursor-pointer [&_>_details_summary]:font-normal [&_>_details_summary]:text-xs [&_>_details_summary]:font-mono max-[760px]:pt-4 max-[760px]:pb-8 px-8 gap-4 max-[760px]:px-4 [&_>_details_summary]:p-3">
    <div className="min-h-45 flex items-end justify-between text-ink bg-paper border border-solid border-line rounded-card [background-image:none] [&_h2]:font-semibold [&_h2]:text-[clamp(var(--text-lg),_2.5vw,_var(--text-2xl))] [&_h2]:leading-[1.13] [&_h2]:font-sans [&_h2]:mt-3 [&_h2]:mb-2 [&_h2]:max-w-180 [&_h2]:wrap-anywhere [&_p]:text-muted [&_p]:font-normal [&_p]:text-2xs [&_p]:font-mono max-[760px]:items-start max-[760px]:flex-col py-6 px-8 gap-6 [&_h2]:mx-0 [&_p]:m-0"><div><p className="font-mono text-2xs text-muted">PDF · DOCX · TXT · XLSX · PNG · JPEG → ortak model</p>
      <h2>AI için ortak doküman çıktısı</h2><p>Metin, tablo ve kaynak kanıtları tek JSON biçiminde. Resimler bu paketin dosya ekleridir.</p></div>
      <a className="border border-solid border-line rounded-sm bg-paper font-normal text-2xs font-mono py-2 px-3" href={`${base}/package`}>Tüm paketi indir · ZIP</a></div>
    <div className={cn(`border border-solid border-ok-line border-l-[4px] border-l-ok rounded-lg bg-ok-soft [&_p]:mt-2 [&_p]:mb-0 [&_p]:text-xs [&_p]:leading-[1.65] [&_p]:text-ink2 my-4 mx-0 py-4 px-5 [&_p]:mx-0 ${output.quality.text_only_complete ? "" : "border-warn-line border-l-warn bg-warn-soft"}`)}>
      <strong>{output.quality.text_only_complete ? "Çıkarılan metin ve tablolar ortak biçimde hazır" : "Ortak biçim hazır · içerik için ek işlem gerekiyor"}</strong>
      <p>{visualGaps ? `${visualGaps} görsel/grafik öğesinin açıklaması eksik. Kaynak dosyası veya native grafik verisi ayrıca incelenmeli. ` : ""}
        {output.quality.gaps.length ? `${output.quality.gaps.length} açık içerik/kapsam kaydı var. ` : ""}
        Kaynaktaki bütün anlamın eksiksiz çıkarıldığı henüz doğrulanmış değil.</p>
    </div>
    <div className="grid grid-cols-[repeat(4,minmax(0,1fr))] border border-solid border-line rounded-card overflow-hidden bg-line max-[1050px]:grid-cols-[repeat(2,1fr)] max-[760px]:grid-cols-[repeat(2,1fr)] gap-1">{[["Metin karakteri", metrics.text_characters], ["Tablo / hücre", `${metrics.tables} / ${metrics.table_cells}`],
      ["Görsel", metrics.visual_nodes], ["Kaynak kanıtı", metrics.evidence]].map(([label,value]) =>
      <div className="bg-paper border border-solid border-line rounded-card min-w-0 [&_h3]:mt-0 [&_h3]:mb-4 [&_h3]:font-semibold [&_h3]:text-lg [&_h3]:font-sans [&_h3]:mx-0 p-4" key={label}><small>{label}</small><strong className="block mt-2 font-semibold text-2xl font-sans">{value}</strong></div>)}</div>
    <div className="flex items-center flex-wrap gap-y-2 gap-x-4 text-xs [&_code]:text-2xs [&_code]:text-muted [&_a]:text-accent my-5 mx-0"><code>docgrain.ai-document · {output.version}</code>
      {[["ai.json","Ortak JSON"],["canonical.md","Okunabilir metin"],["canonical.json","Canonical JSON"],["chunks.jsonl","Chunks"],["manifest.json","Kapsam / checksum"],["ai.schema.json","JSON Schema"]].map(([name,label]) =>
        <a key={name} href={`${base}/outputs/${name}`}>{label} ↓</a>)}</div>
    <div className="flex flex-wrap [&_button]:border [&_button]:border-solid [&_button]:border-line [&_button]:rounded-sm [&_button]:bg-paper [&_button]:font-normal [&_button]:text-2xs [&_button]:font-mono [&_button[aria-pressed='true']]:bg-accent [&_button[aria-pressed='true']]:text-on-accent [&_button[aria-pressed='true']]:border-accent mb-4 gap-1 [&_button]:py-2 [&_button]:px-3">{[["content","İçerik"],["gaps",`Eksikler (${output.quality.gaps.length})`],["json","Ortak JSON"]].map(([key,label]) =>
      <Button variant="ghost" key={key} aria-pressed={view === key} onClick={() => setView(key)}>{label}</Button>)}</div>
    {view === "gaps" && <div className="grid gap-2">{output.quality.gaps.length ? output.quality.gaps.map((gap,index) =>
      <div className="bg-paper border border-solid border-line border-l-[3px] border-l-warn rounded-sm [&_>_div]:flex [&_>_div]:items-center [&_>_div]:mb-2 [&_strong]:text-xs py-3 px-4 [&_>_div]:gap-2" key={`${gap.object_id}-${index}`}><strong>{gapLabel(gap)[0]}</strong>
        <p>{gapLabel(gap)[1]}</p><details><summary>Kayıt ayrıntısı</summary><code>{gap.code}</code><p>{gap.detail}</p>{gap.object_id && <code>{gap.object_id}</code>}</details></div>) :
      <div className="border border-dashed border-line rounded-lg bg-paper text-ink2 [&_strong]:font-semibold [&_strong]:text-md [&_strong]:font-sans [&_p]:mt-1 [&_p]:mb-0 [&_p]:text-muted [&_p]:text-xs py-10 px-6 [&_p]:mx-0"><strong>Kayıtlı çıkarım eksiği yok</strong><p>Bu durum kaynak belgedeki bütün bilginin bağımsız doğrulaması değildir.</p></div>}</div>}
    {view === "json" && <><Button variant="ghost" className="h-auto whitespace-normal border border-solid border-line rounded-sm bg-paper font-normal text-2xs font-mono py-2 px-3" onClick={async () => {
      try { await navigator.clipboard.writeText(JSON.stringify(output,null,2)); setCopyState("Kopyalandı"); }
      catch { setCopyState("Kopyalanamadı; JSON dosyasını indirebilirsin."); }
    }}>JSON kopyala</Button> <span>{copyState}</span><pre className="bg-sunken text-ink2 rounded-lg whitespace-pre-wrap wrap-anywhere overflow-auto max-h-[650px] font-normal text-2xs leading-[1.6] font-mono mt-0 mb-2 mx-2 p-4">{JSON.stringify(output,null,2)}</pre></>}
    {view === "content" && <div className="grid gap-3">{output.content.filter(n => n.kind !== "document" && n.kind !== "list").map(node => {
      const asset = output.assets.find(a => a.artifact.id === node.artifact_id);
      const ids = Array.from(new Set([...node.annotation.provenance.evidence_ids,
        ...Object.values(node.field_annotations).flatMap(a => a.provenance.evidence_ids),
        ...(node.rows ?? []).flatMap(row => row.flatMap(c => c.annotation?.provenance.evidence_ids ?? []))]));
      return <article className="min-w-0 border border-solid border-line rounded-lg bg-paper [&_h3]:mt-0 [&_h3]:mb-3 [&_h3]:font-semibold [&_h3]:text-xl [&_h3]:font-sans [&_h3_small]:font-normal [&_h3_small]:text-2xs [&_h3_small]:font-sans [&_h3_small]:text-muted [&_p]:text-sm [&_p]:leading-[1.8] [&_details]:mt-4 [&_details]:text-2xs [&_details]:text-muted [&_summary]:cursor-pointer [&_summary]:mb-2 py-4 px-5 [&_h3]:mx-0" key={node.id}>
        {node.annotation.provenance.confidence_method?.startsWith("easyocr") && <p className="text-muted text-xs leading-[1.55]">
          {node.annotation.provenance.confidence_method.endsWith(":mixed") ? "Native metin + OCR" : "OCR metni"} · kaynakla doğrulanmadı</p>}
        {node.kind === "section" && <h3>{node.heading}</h3>}
        {node.kind === "text_block" && <p className="whitespace-pre-wrap wrap-anywhere">{node.text}</p>}
        {node.kind === "table" && <><h3>{node.caption || "Tablo"} <small>{node.rows?.length} satır</small></h3>
          <div className="max-w-full overflow-auto mt-4 border border-solid border-line rounded-sm"><Table containerClassName="overflow-visible" className="[&_td]:whitespace-normal border-collapse font-normal text-2xs leading-[1.45] font-sans w-full [&_td]:border [&_td]:border-solid [&_td]:border-line [&_td]:min-w-[90px] [&_td]:align-[top] [&_tr:nth-child(even)]:bg-sheet [&_td_small]:block [&_td_small]:text-faint [&_td_small]:font-normal [&_td_small]:text-2xs [&_td_small]:font-mono [&_td_small]:mt-1 [&_td]:p-2"><TableBody>{node.rows?.map((row,r) => <TableRow key={r}>{row.map((cell,c) =>
            <TableCell key={c}>{cell.value == null ? "∅" : valueText(cell.value)}
              {cell.formula && <small>Formül: {cell.formula} · cached: {valueText(cell.cached_value)}</small>}
              {(cell.row_span > 1 || cell.col_span > 1) && <small>Birleşik hücre: {cell.row_span} × {cell.col_span}</small>}
              {cell.display_text != null && cell.display_text !== valueText(cell.value) && <small>Kaynak gösterimi: {cell.display_text}</small>}
              {cell.source_attributes?.number_format != null && <small>Sayı biçimi: {String(cell.source_attributes.number_format)}</small>}
              {cell.source_attributes?.data_type != null && <small>Kaynak türü: {String(cell.source_attributes.data_type)}</small>}
              {cell.source_attributes?.parser_text != null && cell.source_attributes.parser_text !== cell.value && <small>Önceki parser metni: {valueText(cell.source_attributes.parser_text)}</small>}
            </TableCell>)}</TableRow>)}</TableBody></Table></div></>}
        {(node.kind === "asset" || node.kind === "chart") && <><h3>{node.description || "Görsel içerik"}</h3>
          {node.source_data && <><strong>Kaynak grafik verisi</strong><p>Seri, kategori, değer ve hücre aralıkları kaynak dosyadan okunur; görsel yorum değildir.</p>
            <pre className="bg-sunken text-ink2 rounded-lg whitespace-pre-wrap wrap-anywhere overflow-auto max-h-[650px] font-normal text-2xs leading-[1.6] font-mono mt-0 mb-2 mx-2 p-4">{JSON.stringify(node.source_data, null, 2)}</pre></>}
          {asset?.artifact.mime_type.startsWith("image/") && <img className="block max-w-[min(100%,640px)] max-h-100 object-contain border border-solid border-line" src={`${API}${asset.api_path}`} alt={node.description || "Kaynak belgeden çıkarılan görsel; içerik henüz yorumlanmadı"} loading="lazy" />}
          <p>{node.description || "Görselin anlamı metin çıktısında yok; OCR veya görsel yorumlama gerekiyor."}</p></>}
        {!!ids.length && <details><summary>Kaynak kanıtları · {ids.length}</summary><div className="flex flex-wrap gap-2">{ids.map(id =>
          <Button variant="ghost" className="h-auto whitespace-normal border border-solid border-accent-line bg-accent-soft rounded-sm text-left flex flex-col max-w-full [&_span]:text-accent [&_span]:text-2xs [&_small]:font-normal [&_small]:text-2xs [&_small]:font-mono [&_small]:text-faint [&_small]:wrap-anywhere [&:hover]:bg-accent-soft p-2" key={id} onClick={() => setSelectedEvidence(id)}>{id}</Button>)}</div></details>}
        {evidence && ids.includes(evidence.id) && <EvidenceView evidence={evidence} snapshot={snapshot} versionId={versionId} />}
      </article>;
    })}</div>}
  </div>;
}
