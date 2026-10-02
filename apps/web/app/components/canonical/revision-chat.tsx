"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import "./revision-chat.css";
import { EvidenceView, type Evidence, type Node, type Snapshot } from "./inspector";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const MAX_IMAGES = 3;
const MAX_QUESTION = 2000;
const IMAGE_MIMES = ["image/jpeg", "image/png"];

type Mode = "live" | "demo";
type Reply = {
  revision_id: string; snapshot_sha256: string; model: string; answer: string; abstained: boolean;
  citations: { node_id: string; evidence: Evidence }[];
  images: { node_id: string; caption: string | null; description: string | null; artifact_url: string; evidence_ids: string[] }[];
  warnings: string[];
};
type Turn = { id: number; question: string; attached: number; reply: Reply };
type Config = { status: "idle" | "loading" | "ready" | "error"; enabled: boolean; model: string };

class HttpError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

async function request<T>(url: string, mode: Mode, init: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const served = response.headers.get("X-Docgrain-Mode");
  if (served && served !== mode) throw new Error("API çalışma modu değişti. Sayfayı yenileyip tekrar deneyin.");
  if (!response.ok) {
    let detail = "";
    try { const body = await response.json(); if (typeof body?.detail === "string") detail = body.detail; } catch { /* non-JSON error body */ }
    throw new HttpError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

const isReply = (value: unknown): value is Reply => {
  const item = value as Partial<Reply> | null;
  return !!item && typeof item === "object" && typeof item.answer === "string" && typeof item.revision_id === "string" &&
    typeof item.snapshot_sha256 === "string" && typeof item.abstained === "boolean" && typeof item.model === "string" &&
    Array.isArray(item.citations) && Array.isArray(item.images) && Array.isArray(item.warnings);
};
const friendlyError = (error: unknown): string => {
  if (error instanceof HttpError) {
    if (error.status === 503) return "Gemini şu anda kullanılamıyor veya sohbet bu sunucuda kapalı. Daha sonra tekrar deneyin.";
    if (error.status === 502) return "Model yanıtı doğrulanamadı, bu yüzden gösterilmedi. Soruyu yeniden ifade edip tekrar deneyin.";
    if (error.status === 409 || error.status === 413 || error.status === 422) return error.message || `İstek reddedildi (${error.status}).`;
    return `İstek tamamlanamadı (${error.status}).`;
  }
  return error instanceof Error ? error.message : "İstek tamamlanamadı.";
};
const nodeEvidenceIds = (node: Node) => new Set([
  ...node.annotation.provenance.evidence_ids,
  ...Object.values(node.field_annotations).flatMap((item) => item.provenance.evidence_ids),
  ...(node.rows ?? []).flatMap((row) => row.flatMap((cell) => cell.annotation?.provenance.evidence_ids ?? [])),
]);
const artifactPath = (revisionId: string, artifactId: string) =>
  `/v1/knowledge/revisions/${encodeURIComponent(revisionId)}/artifacts/${encodeURIComponent(artifactId)}`;

function sourceLabel(evidence: Evidence): string {
  const locator = evidence.locator;
  switch (locator.kind) {
    case "pdf_page": return `Sayfa ${locator.page_number}`;
    case "spreadsheet_range": return `${locator.sheet} · ${locator.a1_range}`;
    case "docx_block": return `Word · ${locator.path}`;
    case "text_span": return `Karakter ${locator.start}–${locator.end}`;
    case "image_region": return "Görseldeki bölge";
    default: return "Kaynak konumu";
  }
}

function ReplyView({ turn, snapshot, versionId }: { turn: Turn; snapshot: Snapshot; versionId?: string }) {
  const { reply } = turn;
  const nodes = useMemo(() => new Map(snapshot.structure.map((node) => [node.id, node])), [snapshot]);
  const revisionId = snapshot.knowledge_revision.id;
  const citations = reply.citations.flatMap((citation) => {
    const node = nodes.get(citation.node_id);
    const evidence = snapshot.evidence.find((item) => item.id === citation.evidence?.id);
    return node && evidence && nodeEvidenceIds(node).has(evidence.id) ? [{ node, evidence }] : [];
  });
  const images = reply.images.flatMap((image) => {
    const node = nodes.get(image.node_id);
    const artifact = node && (node.kind === "asset" || node.kind === "chart") ?
      snapshot.artifacts.find((item) => item.id === node.artifact_id) : undefined;
    return node && artifact && IMAGE_MIMES.includes(artifact.mime_type) && image.artifact_url === artifactPath(revisionId, artifact.id) ?
      [{ image, node, src: `${API}${image.artifact_url}` }] : [];
  });
  const hidden = reply.citations.length - citations.length + reply.images.length - images.length;
  return <article className="rc-turn">
    <p className="rc-question"><span>Soru</span>{turn.question}{turn.attached > 0 && <small> · {turn.attached} görsel eklendi</small>}</p>
    <div className={`rc-answer${reply.abstained ? " is-abstained" : ""}`}>
      <span className="rc-kicker">{reply.abstained ? "Model yanıt vermedi" : "Model yanıtı"} · {reply.model}</span>
      <p>{reply.answer}</p>
    </div>
    {reply.warnings.map((warning, i) => <p className="rc-warning" key={i}>{warning}</p>)}
    {hidden > 0 && <p className="rc-warning">{hidden} atıf veya görsel bu revision ile eşleşmediği için gizlendi.</p>}
    {citations.length > 0 && <div className="rc-block"><span className="rc-kicker">Atıflar · kaynak izi</span>
      {citations.map(({ node, evidence }, index) => <details key={`${node.id}-${evidence.id}`} className="rc-cite">
        <summary>Kaynak {index + 1} · {sourceLabel(evidence)}</summary>
        <EvidenceView evidence={evidence} snapshot={snapshot} versionId={versionId} />
      </details>)}</div>}
    {images.length > 0 && <div className="rc-block"><span className="rc-kicker">Yanıtla ilgili görseller</span>
      <div className="rc-images">{images.map(({ image, node, src }) => <figure key={node.id}>
        <img src={src} alt={image.caption || image.description || "Belgeden çıkarılan görsel"} loading="lazy" />
        <figcaption>{image.caption || "Başlık yok"}{image.description ? ` · ${image.description}` : " · açıklama yok"}</figcaption>
      </figure>)}</div></div>}
  </article>;
}

export function RevisionChat({ snapshot, mode, snapshotSha256, versionId, revisionLabel }: {
  snapshot: Snapshot; mode: Mode | null; snapshotSha256?: string | null; versionId?: string; revisionLabel?: string;
}) {
  const revisionId = snapshot.knowledge_revision.id;
  const [config, setConfig] = useState<Config>({ status: "idle", enabled: false, model: "" });
  const [question, setQuestion] = useState("");
  const [allow, setAllow] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const busyRef = useRef(false);
  const askCtl = useRef<AbortController | null>(null);
  const seq = useRef(0);
  const turnId = useRef(0);

  const imageNodes = useMemo(() => snapshot.structure.filter((node) => {
    if (node.kind !== "asset" && node.kind !== "chart") return false;
    const artifact = snapshot.artifacts.find((item) => item.id === node.artifact_id);
    return !!artifact && artifact.role === "source-image" && IMAGE_MIMES.includes(artifact.mime_type);
  }), [snapshot]);

  // Pinned revision (or mode) changed: abort, and drop the whole session that belonged to the previous one.
  useEffect(() => {
    askCtl.current?.abort(); seq.current += 1; busyRef.current = false;
    setBusy(false); setError(""); setTurns([]); setSelected([]); setAllow(false); setQuestion("");
    return () => { askCtl.current?.abort(); seq.current += 1; };
  }, [revisionId, mode]);

  // The only automatic call: a safe, read-only config probe.
  useEffect(() => {
    if (mode !== "live") { setConfig({ status: "idle", enabled: false, model: "" }); return; }
    const ctl = new AbortController();
    setConfig({ status: "loading", enabled: false, model: "" });
    request<{ enabled?: unknown; model?: unknown }>(`${API}/v1/knowledge/revisions/${encodeURIComponent(revisionId)}/chat/config`, mode, { signal: ctl.signal })
      .then((data) => {
        if (ctl.signal.aborted) return;
        setConfig({ status: "ready", enabled: data.enabled === true, model: typeof data.model === "string" ? data.model : "" });
      }).catch(() => { if (!ctl.signal.aborted) setConfig({ status: "error", enabled: false, model: "" }); });
    return () => ctl.abort();
  }, [mode, revisionId]);

  const trimmed = question.trim();
  const canAsk = mode === "live" && config.enabled && allow && !busy && trimmed.length > 0 && question.length <= MAX_QUESTION;

  async function ask() {
    if (!canAsk || busyRef.current || mode !== "live") return;
    const ctl = new AbortController();
    askCtl.current = ctl; busyRef.current = true;
    const mine = ++seq.current;
    const sent = question, images = [...selected];
    setBusy(true); setError("");
    try {
      let digest = snapshotSha256 ?? "";
      if (!digest) {
        // Explicit, user-triggered read of the pinned revision's digest; it is not sent anywhere else.
        const review = await request<{ snapshot_sha256?: unknown; snapshot?: { knowledge_revision?: { id?: string } } }>(
          `${API}/v1/documents/${encodeURIComponent(snapshot.document_id)}/review?revision_id=${encodeURIComponent(revisionId)}`, mode, { signal: ctl.signal });
        if (review.snapshot?.knowledge_revision?.id !== revisionId || typeof review.snapshot_sha256 !== "string") throw new Error("Revision özeti doğrulanamadı.");
        digest = review.snapshot_sha256;
      }
      const data = await request<unknown>(`${API}/v1/knowledge/revisions/${encodeURIComponent(revisionId)}/chat`, mode, {
        method: "POST", headers: { "content-type": "application/json" }, signal: ctl.signal,
        body: JSON.stringify({ snapshot_sha256: digest, question: sent, allow_remote: true, image_node_ids: images }),
      });
      if (mine !== seq.current) return;
      if (!isReply(data) || data.revision_id !== revisionId || data.snapshot_sha256 !== digest) throw new Error("Yanıt bu revision ile eşleşmedi, bu yüzden gösterilmedi.");
      setTurns((previous) => [{ id: ++turnId.current, question: sent, attached: images.length, reply: data }, ...previous]);
      setQuestion("");
    } catch (caught) {
      if (mine !== seq.current || ctl.signal.aborted) return;
      setError(friendlyError(caught));
    } finally {
      if (mine === seq.current) { busyRef.current = false; setBusy(false); setAllow(false); }
    }
  }

  const toggle = (id: string) => setSelected((previous) =>
    previous.includes(id) ? previous.filter((item) => item !== id) : previous.length < MAX_IMAGES ? [...previous, id] : previous);

  if (mode === "demo") return <div className="rc"><div className="rc-empty"><strong>Belge sohbeti demo modunda kullanılamıyor</strong>
    <p>Demo verileri sentetiktir; model çağrısı yapılmaz.</p></div></div>;
  if (mode === null) return <div className="rc"><div className="rc-empty"><strong>API bekleniyor</strong><p>Çalışma modu doğrulandığında sohbet açılır.</p></div></div>;

  return <div className="rc" aria-busy={busy}>
    <header className="rc-head">
      <div><span className="rc-kicker">Deneysel · belge sohbeti</span><h2>Bu revision hakkında soru sor</h2></div>
      <div className="rc-badges">
        <span className="rc-chip rc-chip-strong">Embedding yok</span>
        <span className="rc-chip">Revision {revisionLabel ?? revisionId.slice(-10)}</span>
        {config.model && <span className="rc-chip">Model: {config.model}</span>}
      </div>
    </header>
    <p className="rc-note">Yanıtlar bir modelin yorumudur ve doğru olduğu garanti edilmez. Sohbet yalnızca bu sabitlenmiş revision’ı kullanır; revision ve kaynak dosya değiştirilmez. Her soru bağımsızdır; önceki mesajlar modele gönderilmez.
      Docgrain sohbet geçmişini sunucuda tutmaz.</p>
    {config.status === "loading" && <p className="rc-note" role="status">Sohbet ayarı kontrol ediliyor…</p>}
    {config.status === "error" && <p className="rc-error" role="alert">Sohbet ayarı okunamadı. Sunucu çalışıyor mu kontrol edin.</p>}
    {config.status === "ready" && !config.enabled && <div className="rc-empty"><strong>Belge sohbeti bu sunucuda kapalı</strong>
      <p>Sunucu ayarı etkinleştirilmediği veya Gemini anahtarı tanımlanmadığı için soru sorulamaz.</p></div>}

    {config.enabled && <section className="rc-form" aria-label="Soru sor">
      <label>Sorunuz<textarea value={question} rows={3} maxLength={MAX_QUESTION} disabled={busy}
        placeholder="Örn. Bu belgedeki toplam tutar nedir?" onChange={(e) => setQuestion(e.target.value)} /></label>
      <small className="rc-count">{question.length} / {MAX_QUESTION}</small>

      {imageNodes.length > 0 && <details className="rc-attachment-picker"><summary>Görsel ekle · {selected.length} seçili / {imageNodes.length} görsel</summary><fieldset className="rc-pick" disabled={busy}>
        <legend>İsteğe bağlı: modele görsel ekle (en fazla {MAX_IMAGES})</legend>
        <div className="rc-thumbs">{imageNodes.map((node, index) => {
          const artifact = snapshot.artifacts.find((item) => item.id === node.artifact_id)!;
          const on = selected.includes(node.id);
          return <label key={node.id} className={`rc-thumb${on ? " is-on" : ""}`}>
            <input type="checkbox" checked={on} disabled={!on && selected.length >= MAX_IMAGES} onChange={() => toggle(node.id)} />
            <img src={`${API}${artifactPath(revisionId, artifact.id)}`} alt="" loading="lazy" />
            <span>{node.caption || `Görsel ${index + 1}`} · <code>{node.id.slice(-8)}</code></span>
          </label>;
        })}</div>
        <small>Etiketler kayıtlı başlıktır; görselin anlamı çıkarılmaz.</small>
      </fieldset></details>}

      <div className="rc-disclosure">
        <strong>Gemini’ye gönderilecekler</strong>
        <p>Yalnızca bu revision’ın kanonik içeriği (metin, tablolar, açıklamalar, kaynak konumları ve kayıtlı eksikler)
          {selected.length > 0 ? ` ile seçtiğiniz ${selected.length} görselin baytları` : ""} Google Gemini’ye gönderilir.
          Özgün PDF/Office dosyası ve seçmediğiniz görseller gönderilmez. Embedding üretilmez.</p>
        <label className="rc-check"><input type="checkbox" checked={allow} disabled={busy} onChange={(e) => setAllow(e.target.checked)} />
          Bu soru için içeriğin Gemini’ye gönderilmesine izin veriyorum.</label>
      </div>
      <div className="rc-row">
        <button type="button" className="rc-btn rc-btn-primary" disabled={!canAsk} onClick={() => void ask()}>{busy ? "Soruluyor…" : "Sor"}</button>
        {!allow && <span className="rc-note">Her soru için onay kutusunu yeniden işaretleyin.</span>}
      </div>
      {error && <p className="rc-error" role="alert">{error}</p>}
    </section>}

    {turns.length > 0 && <section className="rc-turns" aria-label="Yanıtlar" aria-live="polite">
      <p className="rc-note">Bu yanıtlar yalnızca bu sayfada durur; sayfa veya revision değişince silinir.</p>
      {turns.map((turn) => <ReplyView key={turn.id} turn={turn} snapshot={snapshot} versionId={versionId} />)}
    </section>}
  </div>;
}
