"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import "./local-visual-proposal.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type LocalVisualConfig = { enabled: boolean; ready: boolean; model: string; profile_id: string };
export type LocalVisualProposalData = {
  id: string; review_status: "proposed"; revision_id: string; snapshot_sha256: string; node_id: string;
  artifact_id: string; binary_sha256: string; profile_id: string; model: string; classification: string;
  description: string | null; visible_text: string[]; uncertainties: string[]; warnings: string[]; elapsed_ms: number;
};
type Props = {
  revisionId: string; snapshotSha256: string; nodeId: string; mode: "live" | "demo" | null;
  canAdopt: boolean; locked: boolean;
  /** Return false when the parent declined (e.g. the reviewer cancelled the overwrite confirmation). */
  onAdopt: (description: string, proposal: LocalVisualProposalData) => boolean | void;
};
type ConfigState =
  | { status: "idle" } | { status: "loading" } | { status: "error"; message: string }
  | { status: "ready"; data: LocalVisualConfig };
type RunState = { status: "idle" | "running" | "error"; message: string };

const CLASSIFICATION_LABEL: Record<string, string> = {
  chart: "Grafik", graph: "Grafik", diagram: "Diyagram", photo: "Fotoğraf", photograph: "Fotoğraf", table: "Tablo",
  text: "Metin ağırlıklı görsel", document: "Belge görüntüsü", screenshot: "Ekran görüntüsü", logo: "Logo",
  map: "Harita", drawing: "Çizim", illustration: "İllüstrasyon", signature: "İmza", handwriting: "El yazısı",
  decorative: "Süs amaçlı görsel", other: "Diğer", unknown: "Belirsiz",
  plan: "Plan",
};
const classificationText = (value: string) => {
  const key = value.trim().toLowerCase();
  return CLASSIFICATION_LABEL[key] ?? (key ? `Tanınmayan sınıf (${value})` : "Belirsiz");
};

const isStrings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === "string");
function isConfig(value: unknown): value is LocalVisualConfig {
  const item = value as Partial<LocalVisualConfig> | null;
  return !!item && typeof item === "object" && typeof item.enabled === "boolean" && typeof item.ready === "boolean" &&
    typeof item.model === "string" && typeof item.profile_id === "string";
}
function isProposal(value: unknown): value is LocalVisualProposalData {
  const item = value as Partial<LocalVisualProposalData> | null;
  return !!item && typeof item === "object" && typeof item.id === "string" && item.review_status === "proposed" &&
    typeof item.revision_id === "string" && typeof item.snapshot_sha256 === "string" && typeof item.node_id === "string" &&
    typeof item.artifact_id === "string" && typeof item.binary_sha256 === "string" && typeof item.profile_id === "string" &&
    typeof item.model === "string" && typeof item.classification === "string" &&
    (item.description === null || typeof item.description === "string") &&
    isStrings(item.visible_text) && isStrings(item.uncertainties) && isStrings(item.warnings) &&
    typeof item.elapsed_ms === "number" && Number.isFinite(item.elapsed_ms);
}

async function call<T>(url: string, mode: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const served = response.headers.get("X-Docgrain-Mode");
  if (served && served !== mode) throw new Error("API çalışma modu değişti. Sayfayı yenileyip tekrar deneyin.");
  if (!response.ok) {
    let detail = `İstek tamamlanamadı (${response.status}).`;
    try {
      const body = (await response.json())?.detail;
      if (typeof body === "string") detail = body;
      else if (Array.isArray(body)) {
        const parts = body.map((part) => part && typeof part === "object" && "msg" in part ? String((part as { msg: unknown }).msg) : "").filter(Boolean);
        if (parts.length) detail = parts.join(" · ");
      }
    } catch { /* non-JSON error body */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function LocalVisualProposal({ revisionId, snapshotSha256, nodeId, mode, canAdopt, locked, onAdopt }: Props) {
  const [config, setConfig] = useState<ConfigState>({ status: "idle" });
  const [configTick, setConfigTick] = useState(0);
  const [run, setRun] = useState<RunState>({ status: "idle", message: "" });
  const [proposal, setProposal] = useState<LocalVisualProposalData | null>(null);
  const [adopted, setAdopted] = useState(false);

  const configCtl = useRef<AbortController | null>(null);
  const runCtl = useRef<AbortController | null>(null);
  const configSeq = useRef(0);
  const runSeq = useRef(0);
  const busy = useRef(false);

  const cancelRun = useCallback(() => {
    runCtl.current?.abort(); runSeq.current += 1; busy.current = false;
  }, []);

  // Anything the proposal is bound to changed: cancel the request and forget the proposal.
  useEffect(() => {
    setProposal(null); setAdopted(false); setRun({ status: "idle", message: "" });
    return () => cancelRun();
  }, [revisionId, snapshotSha256, nodeId, mode, cancelRun]);

  useEffect(() => {
    if (mode !== "live") { setConfig({ status: "idle" }); return; }
    const ctl = new AbortController();
    configCtl.current = ctl;
    const seq = ++configSeq.current;
    setConfig({ status: "loading" });
    call<unknown>(`${API}/v1/knowledge/revisions/${encodeURIComponent(revisionId)}/visuals/local/config`, mode, { signal: ctl.signal })
      .then((data) => {
        if (ctl.signal.aborted || seq !== configSeq.current) return;
        if (!isConfig(data)) throw new Error("Yerel model durumu beklenen biçimde değil.");
        setConfig({ status: "ready", data });
      }).catch((error: unknown) => {
        if (ctl.signal.aborted || seq !== configSeq.current) return;
        setConfig({ status: "error", message: error instanceof Error ? error.message : "Yerel model durumu alınamadı." });
      });
    return () => { ctl.abort(); configSeq.current += 1; };
  }, [revisionId, mode, configTick]);

  async function generate() {
    if (mode !== "live" || busy.current || locked || config.status !== "ready" || !config.data.enabled || !config.data.ready) return;
    const ctl = new AbortController();
    runCtl.current = ctl; busy.current = true;
    const seq = ++runSeq.current;
    const sent = { revisionId, snapshotSha256, nodeId };
    setRun({ status: "running", message: "" });
    try {
      const data = await call<unknown>(`${API}/v1/knowledge/revisions/${encodeURIComponent(revisionId)}/visuals/local/proposals`, mode, {
        method: "POST", headers: { "content-type": "application/json" }, signal: ctl.signal,
        body: JSON.stringify({ snapshot_sha256: snapshotSha256, node_id: nodeId }),
      });
      if (ctl.signal.aborted || seq !== runSeq.current) return;
      if (!isProposal(data)) throw new Error("Yerel model yanıtı beklenen biçimde değil; öneri gösterilmedi.");
      if (data.revision_id !== sent.revisionId || data.snapshot_sha256 !== sent.snapshotSha256 || data.node_id !== sent.nodeId) {
        throw new Error("Yanıt bu görsel veya revision ile eşleşmiyor; öneri reddedildi. Tekrar deneyin.");
      }
      setProposal(data); setAdopted(false); setRun({ status: "idle", message: "" });
    } catch (error) {
      if (ctl.signal.aborted || seq !== runSeq.current) return;
      setRun({ status: "error", message: error instanceof Error ? error.message : "Yerel model önerisi alınamadı." });
    } finally {
      if (seq === runSeq.current) busy.current = false;
    }
  }

  function cancel() {
    cancelRun();
    setRun({ status: "idle", message: "" });
  }

  function adopt() {
    if (!proposal || !canAdopt || locked || adopted) return;
    if (proposal.revision_id !== revisionId || proposal.snapshot_sha256 !== snapshotSha256 || proposal.node_id !== nodeId) return;
    if (proposal.description === null || proposal.description.trim() === "") return;
    if (onAdopt(proposal.description, proposal) !== false) setAdopted(true);
  }

  function download() {
    if (!proposal) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(proposal, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url; link.download = `yerel-gorsel-onerisi-${proposal.id.replace(/[^A-Za-z0-9_-]/g, "_")}.json`;
    document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  if (mode !== "live") return null;
  const running = run.status === "running";
  const ready = config.status === "ready" && config.data.enabled && config.data.ready;
  const hasDescription = !!proposal && proposal.description !== null && proposal.description.trim() !== "";

  return <section className="lvp" aria-label="Yerel model açıklama önerisi" aria-busy={running} onClick={(e) => e.stopPropagation()}>
    <div className="lvp-head">
      <span className="rw-kicker">Yerel model önerisi</span>
      {config.status === "ready" && config.data.enabled && <span className="rw-chip">{config.data.model || "model belirtilmemiş"}</span>}
    </div>
    <p className="rw-note">Öneri yalnızca bu bilgisayardaki yerel modelle üretilir; bulut modeline gönderilmez. Model çıktısı hatalı olabilir, kaynakla karşılaştırmadan kullanmayın. Öneri üretmek revision oluşturmaz ve belgeyi değiştirmez.</p>

    {config.status === "loading" && <p className="rw-note" role="status">Yerel model durumu denetleniyor…</p>}
    {config.status === "error" && <div className="lvp-problem" role="alert"><p className="rw-error">Yerel model durumu alınamadı: {config.message}</p>
      <button type="button" className="rw-btn" onClick={() => setConfigTick((t) => t + 1)}>Durumu yeniden denetle</button></div>}
    {config.status === "ready" && !config.data.enabled && <div className="lvp-problem" role="status">
      <p className="rw-note rw-note-warn">Yerel görsel açıklama bu ortamda kapalı. Elle açıklama yazmaya devam edebilirsiniz.</p>
      <button type="button" className="rw-btn" onClick={() => setConfigTick((t) => t + 1)}>Durumu yeniden denetle</button></div>}
    {config.status === "ready" && config.data.enabled && !config.data.ready && <div className="lvp-problem" role="status">
      <p className="rw-note rw-note-warn">Yerel model henüz hazır değil{config.data.model ? ` (${config.data.model})` : ""}. Hazır olduğunda yeniden denetleyin.</p>
      <button type="button" className="rw-btn" onClick={() => setConfigTick((t) => t + 1)}>Durumu yeniden denetle</button></div>}

    <div className="rw-row">
      <button type="button" className="rw-btn" disabled={!ready || running || locked} onClick={() => void generate()}>
        {running ? "Yerel model çalışıyor…" : "Yerel modelle açıklama öner"}</button>
      {running && <button type="button" className="rw-btn rw-btn-warn" onClick={cancel}>İptal et</button>}
    </div>
    {running && <p className="rw-note" role="status">Açıklama üretiliyor; bu birkaç dakika sürebilir. Taslaklarınıza dokunulmaz.</p>}
    {run.status === "error" && <div className="lvp-problem" role="alert">
      <p className="rw-error">{run.message}</p>
      <p className="rw-note">Taslaklarınız korundu; düğmeye yeniden basarak tekrar deneyebilirsiniz.</p></div>}

    {proposal && <div className={`lvp-result${running ? " is-stale" : ""}`}>
      <div className="lvp-chips">
        <span className="rw-chip rw-chip-draft">Yerel model önerisi · doğrulanmadı</span>
        <span className="rw-chip">Sınıf: {classificationText(proposal.classification)}</span>
        <span className="rw-chip">Model: {proposal.model}</span>
        <span className="rw-chip">Profil: {proposal.profile_id}</span>
        <span className="rw-chip">{(proposal.elapsed_ms / 1000).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} sn</span>
      </div>
      <div className="lvp-field">
        <span>Önerilen açıklama</span>
        {hasDescription ? <blockquote className="lvp-text">{proposal.description}</blockquote>
          : <p className="rw-note rw-note-warn">Model bu görsel için açıklama üretmedi; taslağa alınamaz.</p>}
      </div>
      <div className="lvp-field">
        <span>Metin çıkarımı</span>
        {proposal.visible_text.length ? <ul className="lvp-list">{proposal.visible_text.map((line, i) => <li key={i}><code>{line}</code></li>)}</ul>
          : <p className="rw-note">Bu model metin çıkarmaz; yazıları ayrı OCR çıktısı ve kaynak üzerinden inceleyin.</p>}
      </div>
      <div className="lvp-field">
        <span>Belirsizlikler</span>
        {proposal.uncertainties.length ? <ul className="lvp-list">{proposal.uncertainties.map((item, i) => <li key={i}>{item}</li>)}</ul>
          : <p className="rw-note">Model belirsizlik bildirmedi; bu, önerinin doğru olduğunu göstermez.</p>}
      </div>
      {proposal.warnings.length > 0 && <div className="lvp-field">
        <span>Uyarılar</span>
        <ul className="lvp-list">{proposal.warnings.map((item, i) => <li key={i} className="rw-note-warn">{item}</li>)}</ul>
      </div>}
      <p className="rw-meta">Öneri kimliği: {proposal.id}</p>
      <div className="rw-row">
        <button type="button" className="rw-btn rw-btn-primary" disabled={!canAdopt || locked || !hasDescription || adopted || running} onClick={adopt}>
          {adopted ? "Taslağa alındı" : "Açıklama taslağına al"}</button>
        <button type="button" className="rw-btn" onClick={download}>Öneriyi JSON olarak indir</button>
      </div>
      {!canAdopt && <p className="rw-note rw-note-warn">Bu görünümde açıklama taslağı düzenlenemiyor (eski revision veya salt okunur alan); öneri yalnızca incelenebilir.</p>}
      {adopted && <p className="rw-note" role="status">Öneri açıklama taslağına alındı. Henüz kaydedilmedi; kaynakla karşılaştırıp gerekirse düzenleyin.</p>}
    </div>}
  </section>;
}
