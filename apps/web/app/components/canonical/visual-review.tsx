"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";


import { useEffect, useRef, useState } from "react";
import type { Snapshot } from "./inspector";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const labels: Record<string, string> = { unknown: "Belirsiz", logo: "Logo", decorative: "Dekoratif",
  photo: "Fotoğraf", table: "Tablo", plan: "Plan", diagram: "Diyagram", chart: "Grafik" };
type Region = { id: string; node_id: string; node_kind: string; classification: string;
  evidence_ids: string[]; binary_available: boolean; duplicate_of: string | null;
  native_chart_data: boolean; description_present: boolean; actions: string[] };
type Inventory = { id: string; snapshot_sha256: string; revision_id: string;
  regions: Region[]; unresolved_picture_refs: string[] };

function download(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename;
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function VisualReview({ snapshot }: { snapshot: Snapshot }) {
  const revision = snapshot.knowledge_revision.id;
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [decisions, setDecisions] = useState<Record<string, string>>({});
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const saveAbort = useRef<AbortController | null>(null);
  const inventoryMatches = inventory?.revision_id === revision;
  useEffect(() => {
    const abort = new AbortController();
    setInventory(null); setError(""); setSaveError(""); setDecisions({}); setReason(""); setMessage(""); setSaving(false);
    fetch(`${API}/v1/knowledge/revisions/${encodeURIComponent(revision)}/visuals`, { signal: abort.signal })
      .then(async response => {
        if (!response.ok) throw new Error(`Görsel envanteri alınamadı (${response.status}).`);
        return response.json();
      }).then(value => { if (!abort.signal.aborted) setInventory(value); })
      .catch(err => { if (!abort.signal.aborted) setError(err.message); });
    return () => { abort.abort(); saveAbort.current?.abort(); saveAbort.current = null; };
  }, [revision, attempt]);

  async function savePreview() {
    if (!inventory || !inventoryMatches || saveAbort.current) return;
    const abort = new AbortController(); saveAbort.current = abort;
    setSaving(true); setSaveError(""); setMessage("");
    try {
      const response = await fetch(`${API}/v1/knowledge/revisions/${encodeURIComponent(revision)}/visuals/preview`, {
        method: "POST", signal: abort.signal, headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inventory_id: inventory.id, snapshot_sha256: inventory.snapshot_sha256,
          decisions: Object.entries(decisions).map(([region_id, classification]) => ({ region_id, classification,
            reviewer_id: reviewer.trim(), reason: reason.trim() })) }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const detail = body?.detail === "classification requires source evidence"
          ? "Seçilen öğenin kaynak kanıtı eksik."
          : "Kaynak/revision bağını ve seçilen öğeleri kontrol edin.";
        throw new Error(`Öneri hazırlanamadı (${response.status}). ${detail}`);
      }
      const preview = await response.json();
      if (abort.signal.aborted) return;
      download(preview, `${preview.id}.json`);
      setMessage("Sınıflandırma önerisi indirildi. Seçimler sunucuya kaydedilmedi; kaynak ve yayımlanmış çıktı değişmedi.");
    } catch (err) { if (!abort.signal.aborted) setSaveError(err instanceof Error ? err.message : String(err)); }
    finally { if (saveAbort.current === abort) { saveAbort.current = null; if (!abort.signal.aborted) setSaving(false); } }
  }

  return <section className="bg-paper border border-solid border-line rounded-card min-w-0 [&_h3]:mt-0 [&_h3]:mb-4 [&_h3]:font-semibold [&_h3]:text-lg [&_h3]:font-sans [&_>_p]:text-xs [&_>_p]:leading-[1.6] [&_>_p]:text-muted [&_select]:max-w-full [&_select]:border [&_select]:border-solid [&_select]:border-line [&_select]:rounded-sm [&_select]:bg-paper [&_button:disabled]:opacity-[.45] [&_button:disabled]:cursor-default [&_h3]:mx-0 p-4 [&_select]:p-2">
    <span className="font-bold text-2xs leading-[1.4] font-mono tracking-[.12em] uppercase text-muted">YEREL GÖRSEL İNCELEME</span><h3>Görsel türü ve yapılacak işlem</h3>
    <p>Türünü kaynaktan belirleyin. Bu panel öneri JSON’u üretir; sınıflandırma, OCR veya görsel anlamın kabulü değildir. Harici model çağrısı yapılmaz.</p>
    {error && <p role="alert">{error} <Button variant="ghost" className="h-auto whitespace-normal border-0 bg-transparent text-accent font-bold text-2xs font-mono py-3 px-0" onClick={() => setAttempt(x => x+1)}>Tekrar dene</Button></p>}
    {(!inventory || !inventoryMatches) && !error && <p>Envanter yükleniyor…</p>}
    {saveError && <p role="alert">{saveError}</p>}
    {inventory && inventoryMatches && <>
      <p>{inventory.regions.filter(r => r.node_kind !== "table").length} görsel/grafik · {inventory.regions.filter(r => r.node_kind === "table").length} tablo · {inventory.regions.filter(r => r.classification === "unknown").length} türü belirsiz</p>
      {inventory.unresolved_picture_refs.length > 0 && <p>{inventory.unresolved_picture_refs.length} resmin binary veya konum kaydı eksik; sınıflandırma ile kapatılamaz.</p>}
      <Button variant="ghost" className="h-auto whitespace-normal border-0 bg-transparent text-accent font-bold text-2xs font-mono py-3 px-0" onClick={() => download(inventory, `${inventory.id}.json`)}>Kaynakla bağlı envanteri indir</Button>
      {inventory.regions.length === 0 ? <p>Bu revision’da görsel, grafik veya tablo düğümü yok.</p> : <>
        <div className="max-w-full overflow-auto mt-4 border border-solid border-line rounded-sm"><Table containerClassName="overflow-visible" className="[&_td]:whitespace-normal border-collapse font-normal text-2xs leading-[1.45] font-sans w-full [&_td]:border [&_td]:border-solid [&_td]:border-line [&_td]:min-w-[90px] [&_td]:align-[top] [&_tr:nth-child(even)]:bg-sheet [&_td_small]:block [&_td_small]:text-faint [&_td_small]:font-normal [&_td_small]:text-2xs [&_td_small]:font-mono [&_td_small]:mt-1 [&_td]:p-2"><TableHeader><TableRow><TableHead>Kaynak öğesi</TableHead><TableHead>Tür önerisi</TableHead><TableHead>Durum / sonraki işlem</TableHead></TableRow></TableHeader><TableBody>
          {inventory.regions.map((region, index) => <TableRow key={region.id}>
            <TableCell><strong>{labels[region.node_kind] ?? "Görsel"} {index+1}</strong><small>{region.node_id}</small><small>{region.evidence_ids.length} kanıt{region.duplicate_of ? " · aynı binary tekrar kullanılmış" : ""}</small></TableCell>
            <TableCell>{region.node_kind === "asset" ? <Select disabled={!region.evidence_ids.length} value={decisions[region.id] ?? "unknown"}
              onValueChange={value => { setDecisions(current => ({ ...current, [region.id]: value })); setMessage(""); }}>
              <SelectTrigger aria-label={`Görsel türü ${index+1}`} className="max-w-full bg-paper"><SelectValue>{labels[decisions[region.id] ?? "unknown"]}</SelectValue></SelectTrigger>
              <SelectContent>{Object.entries(labels).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent>
            </Select> : <span>{labels[region.classification]} · kaynak yapısı</span>}</TableCell>
            <TableCell>{region.node_kind === "table" ? "Hücreleri kaynakla karşılaştır" : <>
              <span>{region.binary_available ? "Binary kaydı var" : "Raster binary yok"}</span>
              {region.actions.includes("local_ocr_available") && <small>Yerel OCR için seçilebilir</small>}
              {region.native_chart_data && <small>Native grafik verisi korunuyor</small>}
              {!region.description_present && <small>Görsel anlamı henüz açıklanmadı</small>}
              {region.actions.includes("missing_source_evidence") && <small>Kaynak kanıtı eksik</small>}
            </>}</TableCell>
          </TableRow>)}
        </TableBody></Table></div>
        <div className="grid grid-cols-[minmax(140px,1fr)_minmax(0,3fr)] mt-4 [&_label]:grid [&_label]:text-xs [&_input]:w-full [&_input]:border [&_input]:border-solid [&_input]:border-line [&_input]:rounded-sm [&_input]:font-normal [&_input]:text-xs [&_input]:font-sans [&_textarea]:w-full [&_textarea]:border [&_textarea]:border-solid [&_textarea]:border-line [&_textarea]:rounded-sm [&_textarea]:font-normal [&_textarea]:text-xs [&_textarea]:font-sans [&_textarea]:min-h-[65px] [&_textarea]:resize-y max-[700px]:grid-cols-[1fr] gap-4 [&_label]:gap-1 [&_input]:p-2 [&_textarea]:p-2"><label>İnceleyen<Input maxLength={200} value={reviewer} onChange={event => setReviewer(event.target.value)} /></label>
          <label>Kaynak inceleme gerekçesi<Textarea maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} placeholder="Seçtiğiniz görsellerin türünü kaynaktan nasıl belirlediniz?" /></label></div>
        <Button variant="ghost" className="h-auto whitespace-normal border-0 bg-transparent text-accent font-bold text-2xs font-mono py-3 px-0" disabled={saving || !Object.keys(decisions).length || !reviewer.trim() || !reason.trim()} onClick={savePreview}>
          {saving ? "Öneri hazırlanıyor…" : "Sınıflandırma önerisini indir"}</Button>
        {message && <p role="status">{message}</p>}
      </>}
    </>}
  </section>;
}
