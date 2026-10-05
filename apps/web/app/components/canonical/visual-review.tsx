"use client";

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

  return <section className="ci-card ci-visual-review">
    <span className="ci-kicker">YEREL GÖRSEL İNCELEME</span><h3>Görsel türü ve yapılacak işlem</h3>
    <p>Türünü kaynaktan belirleyin. Bu panel öneri JSON’u üretir; sınıflandırma, OCR veya görsel anlamın kabulü değildir. Harici model çağrısı yapılmaz.</p>
    {error && <p role="alert">{error} <button className="ci-text-button" onClick={() => setAttempt(x => x+1)}>Tekrar dene</button></p>}
    {(!inventory || !inventoryMatches) && !error && <p>Envanter yükleniyor…</p>}
    {saveError && <p role="alert">{saveError}</p>}
    {inventory && inventoryMatches && <>
      <p>{inventory.regions.filter(r => r.node_kind !== "table").length} görsel/grafik · {inventory.regions.filter(r => r.node_kind === "table").length} tablo · {inventory.regions.filter(r => r.classification === "unknown").length} türü belirsiz</p>
      {inventory.unresolved_picture_refs.length > 0 && <p>{inventory.unresolved_picture_refs.length} resmin binary veya konum kaydı eksik; sınıflandırma ile kapatılamaz.</p>}
      <button className="ci-text-button" onClick={() => download(inventory, `${inventory.id}.json`)}>Kaynakla bağlı envanteri indir</button>
      {inventory.regions.length === 0 ? <p>Bu revision’da görsel, grafik veya tablo düğümü yok.</p> : <>
        <div className="ci-table-scroll"><table className="ci-data-table"><thead><tr><th>Kaynak öğesi</th><th>Tür önerisi</th><th>Durum / sonraki işlem</th></tr></thead><tbody>
          {inventory.regions.map((region, index) => <tr key={region.id}>
            <td><strong>{labels[region.node_kind] ?? "Görsel"} {index+1}</strong><small>{region.node_id}</small><small>{region.evidence_ids.length} kanıt{region.duplicate_of ? " · aynı binary tekrar kullanılmış" : ""}</small></td>
            <td>{region.node_kind === "asset" ? <select disabled={!region.evidence_ids.length} aria-label={`Görsel türü ${index+1}`} value={decisions[region.id] ?? "unknown"}
              onChange={event => { setDecisions(current => ({ ...current, [region.id]: event.target.value })); setMessage(""); }}>
              {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select> : <span>{labels[region.classification]} · kaynak yapısı</span>}</td>
            <td>{region.node_kind === "table" ? "Hücreleri kaynakla karşılaştır" : <>
              <span>{region.binary_available ? "Binary kaydı var" : "Raster binary yok"}</span>
              {region.actions.includes("local_ocr_available") && <small>Yerel OCR için seçilebilir</small>}
              {region.native_chart_data && <small>Native grafik verisi korunuyor</small>}
              {!region.description_present && <small>Görsel anlamı henüz açıklanmadı</small>}
              {region.actions.includes("missing_source_evidence") && <small>Kaynak kanıtı eksik</small>}
            </>}</td>
          </tr>)}
        </tbody></table></div>
        <div className="ci-review-fields"><label>İnceleyen<input maxLength={200} value={reviewer} onChange={event => setReviewer(event.target.value)} /></label>
          <label>Kaynak inceleme gerekçesi<textarea maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} placeholder="Seçtiğiniz görsellerin türünü kaynaktan nasıl belirlediniz?" /></label></div>
        <button className="ci-text-button" disabled={saving || !Object.keys(decisions).length || !reviewer.trim() || !reason.trim()} onClick={savePreview}>
          {saving ? "Öneri hazırlanıyor…" : "Sınıflandırma önerisini indir"}</button>
        {message && <p role="status">{message}</p>}
      </>}
    </>}
  </section>;
}
