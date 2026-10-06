"use client";

import { useEffect, useState } from "react";
import { useDeveloperMode } from "../developer-mode";
import { Head, Ep, Icon } from "../console-ui";
import { CollectionCard } from "../collection-card";
import { getCollectionLabel, getFieldLabel } from "./labels";
import type { Question } from "../question-card";
import type { CollectionSummary, LoadState } from "../workspace-review";

type Evidence = { document_id: string; document_name?: string; locator: string; quote: string };
type FieldMeta = {
  lang?: string; review_state?: string; evidence?: Evidence[];
  i18n?: Record<string, Evidence[]>; i18n_review_state?: Record<string, string>;
};
type RecordRow = {
  id: string; _meta?: { review_state?: string; fields?: Record<string, FieldMeta>; conflicts?: { field: string; lang: string }[] };
  i18n?: Record<string, Record<string, unknown>>; [field: string]: unknown;
};
type CollectionResult = { rows: RecordRow[]; failed: boolean };
const visibleFields = (row: RecordRow) => Object.keys(row).filter(key => !["id", "_meta", "i18n"].includes(key));
function recordTitle(row: RecordRow) {
  return [row.name, row.title, ...visibleFields(row).map(key => row[key])].find(value => typeof value === "string" && value.trim()) as string || "Kayıt detayı";
}
function valueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Evet" : "Hayır";
  if (Array.isArray(value)) return value.map(valueText).join(", ");
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${getFieldLabel(key)}: ${valueText(item)}`).join(" · ");
  return String(value);
}
function recordSummary(row: RecordRow) {
  return visibleFields(row).filter(key => row[key] !== recordTitle(row) && row[key] !== null && row[key] !== undefined)
    .slice(0, 3).map(key => `${getFieldLabel(key)}: ${valueText(row[key])}`).join(" · ");
}
function ReviewBadge({ state }: { state?: string }) {
  const label = state === "accepted" ? "Onaylandı" : state === "proposed" ? "Öneri" : state === "needs_review" ? "İnceleme bekliyor" : state === "rejected" ? "Reddedildi" : "";
  return label ? <span className={`reviewBadge ${state}`}>{label}</span> : null;
}
function EvidenceView({ evidence, developerMode, documentNames }: { evidence?: Evidence[]; developerMode: boolean; documentNames: Record<string, string> }) {
  if (!evidence?.length) return null;
  return <details className="recordEvidence"><summary>Kaynakta göster</summary><ul>{evidence.map((item, index) => <li key={index}>
    <span>{item.document_name || documentNames[item.document_id] || (developerMode ? item.document_id : `Kaynak belge ${index + 1}`)}{item.locator ? ` · ${item.locator}` : ""}</span>
    <blockquote>“{item.quote}”</blockquote>
  </li>)}</ul></details>;
}

export function InformationView({ apiUrl, workspaceId, initialCollection, summaries, questions, questionState, onQuestion, documentNames = {} }: {
  apiUrl: string; workspaceId: string; initialCollection?: string;
  summaries: CollectionSummary[]; questions: Question[]; questionState: LoadState;
  onQuestion: (question: Question) => void; documentNames?: Record<string, string>;
}) {
  const developerMode = useDeveloperMode();
  const [mode, setMode] = useState<"preview" | "approved">("preview");
  const [state, setState] = useState<LoadState>("loading");
  const [revision, setRevision] = useState("");
  const [collections, setCollections] = useState<string[]>([]);
  const [results, setResults] = useState<Record<string, CollectionResult>>({});
  const [selectedCollection, setSelectedCollection] = useState(initialCollection ?? "");
  const [selectedRecord, setSelectedRecord] = useState<RecordRow | null>(null);
  const [showLanguages, setShowLanguages] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const base = `${apiUrl}/v1/workspaces/${encodeURIComponent(workspaceId)}`;

  useEffect(() => {
    const controller = new AbortController();
    setState("loading"); setResults({}); setSelectedRecord(null); setRevision(""); setCollections([]);
    async function read<T>(url: string): Promise<T> {
      const response = await fetch(url, { signal: controller.signal, cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    }
    async function load() {
      try {
        const revisions = await read<string[]>(`${base}/revisions`);
        if (controller.signal.aborted) return;
        if (!Array.isArray(revisions)) throw new Error("Invalid revisions");
        if (!revisions.length) { setState("ready"); return; }
        const latest = revisions[0];
        const response = await read<{ collections: string[] }>(`${base}/revisions/${encodeURIComponent(latest)}/collections?mode=${mode}`);
        if (!Array.isArray(response.collections)) throw new Error("Invalid collections");
        if (controller.signal.aborted) return;
        setRevision(latest); setCollections(response.collections); setState("ready");
        setSelectedCollection(previous => response.collections.includes(previous) ? previous : "");
        await Promise.allSettled(response.collections.map(async key => {
          try {
            const rows = await read<RecordRow[]>(`${base}/revisions/${encodeURIComponent(latest)}/collections/${encodeURIComponent(key)}?mode=${mode}`);
            if (!Array.isArray(rows)) throw new Error("Invalid records");
            if (!controller.signal.aborted) setResults(previous => ({ ...previous, [key]: { rows, failed: false } }));
          } catch {
            if (!controller.signal.aborted) setResults(previous => ({ ...previous, [key]: { rows: [], failed: true } }));
          }
        }));
      } catch (error) {
        if (!controller.signal.aborted) setState(error instanceof Error && ["404", "405", "501"].includes(error.message) ? "missing" : "error");
      }
    }
    void load();
    return () => controller.abort();
  }, [base, mode, refreshKey]);

  const labelFor = (key: string) => summaries.find(item => item.key === key)?.label || getCollectionLabel(key);
  const questionFor = (field: string, lang?: string) => questions.find(item => item.collection === selectedCollection && item.record_id === selectedRecord?.id && item.field === field && (!lang || item.lang === lang));
  const questionButton = (question?: Question) => question && <button className="fieldQuestion" onClick={() => onQuestion(question)} aria-label={`${question.field_label}: açık soruyu cevapla`} title="Bu bilgi için bir soru var"><span className="conflictDot" aria-hidden="true" /></button>;
  const retry = () => setRefreshKey(value => value + 1);
  const result = results[selectedCollection];

  return <><Head title="Koleksiyonlar" sub="Belgelerinizden derlenen kayıtları ve kaynaklarını inceleyin." endpoint={revision ? `GET /v1/workspaces/${workspaceId}/revisions/${revision}/collections` : ""}>
    <label className="switch"><input type="checkbox" role="switch" checked={mode === "approved"} onChange={event => { setMode(event.target.checked ? "approved" : "preview"); setSelectedCollection(""); }} />Yalnızca onaylı bilgiler</label>
  </Head><div className="wrap">
    {state === "loading" ? <div className="card statePanel" role="status"><span className="loadingLine" /><h2>Koleksiyonlar hazırlanıyor…</h2><p>Şirketinizin kayıtları alınıyor.</p></div> : state !== "ready" ? <div className="card statePanel" role={state === "error" ? "alert" : "status"}><Icon name="grid" /><h2>{state === "missing" ? "Koleksiyonlar henüz hazır değil" : "Koleksiyonlar alınamadı"}</h2><p>Biraz sonra tekrar deneyebilirsiniz.</p><button className="btn" onClick={retry}>Tekrar dene</button></div> : !collections.length ? <div className="card statePanel"><Icon name="grid" /><h2>Henüz koleksiyon yok</h2><p>Belgelerinizden derlenen kayıtlar burada görünecek.</p></div> : !selectedCollection ? <div className="collectionGrid">{collections.map(key => {
      const data = results[key];
      const summary = summaries.find(item => item.key === key);
      const collection = summary ?? { key, label: labelFor(key), records: data?.rows.length ?? 0, conflicts: data?.rows.reduce((sum, row) => sum + (row._meta?.conflicts?.length ?? 0), 0) ?? 0, needs_review: data?.rows.filter(row => row._meta?.review_state !== "accepted").length ?? 0 };
      return !summary && !data ? <div className="card collectionCard" key={key} role="status"><Icon name="grid" /><h3>{labelFor(key)}</h3><p>Kayıtlar yükleniyor…</p></div> : !summary && data?.failed ? <div className="card collectionCard" key={key} role="alert"><h3>{labelFor(key)}</h3><p>Kayıtlar alınamadı.</p><button className="textButton" onClick={retry}>Tekrar dene</button></div> : <CollectionCard key={key} collection={collection} onOpen={() => { setSelectedCollection(key); setSelectedRecord(null); }} />;
    })}</div> : <>
      <div className="recordHeading"><button className="btn" onClick={() => { if (selectedRecord) setSelectedRecord(null); else setSelectedCollection(""); }}>← {selectedRecord ? labelFor(selectedCollection) : "Koleksiyonlar"}</button><h2>{selectedRecord ? recordTitle(selectedRecord) : labelFor(selectedCollection)}</h2>{selectedRecord && <ReviewBadge state={selectedRecord._meta?.review_state} />}</div>
      {questionState === "error" || questionState === "missing" ? <p className="collectionWarning">Açık sorular şu anda gösterilemiyor. Sorular bölümünden tekrar deneyebilirsiniz.</p> : null}
      {!result ? <div className="card statePanel" role="status"><h2>Kayıtlar yükleniyor…</h2></div> : result.failed ? <div className="card statePanel" role="alert"><h2>Kayıtlar alınamadı</h2><p>Bu koleksiyonun kayıtlarını yeniden yükleyin.</p><button className="btn" onClick={retry}>Tekrar dene</button></div> : !result.rows.length ? <div className="card statePanel"><h2>Bu koleksiyonda kayıt yok</h2><p>{mode === "approved" ? "Önizlemedeki bilgileri görmek için onaylı bilgi filtresini kapatın." : "Yeni kayıtlar derlendiğinde burada görünecek."}</p></div> : !selectedRecord ? <div className="recordList">{result.rows.map(row => <button key={row.id} className="card recordRow" onClick={() => setSelectedRecord(row)}><div><strong>{recordTitle(row)}</strong><ReviewBadge state={row._meta?.review_state} /><p>{recordSummary(row)}</p>{developerMode && <Ep>{row.id}</Ep>}</div><Icon name="arrow" /></button>)}</div> : <>
        <div className="collectionToolbar"><label className="switch"><input type="checkbox" role="switch" checked={showLanguages} onChange={event => setShowLanguages(event.target.checked)} />Diğer dilleri göster</label>{questionState === "loading" && <span className="collectionWarning" role="status">Açık sorular yükleniyor…</span>}</div>
        <section className="card"><dl className="recordFields">{visibleFields(selectedRecord).map(field => {
          const meta = selectedRecord._meta?.fields?.[field];
          return <div className="recordField" key={field}><dt>{getFieldLabel(field)}{questionButton(questionFor(field))}{developerMode && <div><Ep>{field}</Ep></div>}</dt><dd>{valueText(selectedRecord[field])}<ReviewBadge state={meta?.review_state} /><EvidenceView evidence={meta?.evidence} developerMode={developerMode} documentNames={documentNames} />
            {showLanguages && Object.entries(selectedRecord.i18n ?? {}).filter(([, fields]) => fields[field] !== undefined).map(([lang, fields]) => <div className="recordTranslation" key={lang}><span>{lang}</span>{valueText(fields[field])}<ReviewBadge state={meta?.i18n_review_state?.[lang]} />{questionButton(questionFor(field, lang))}<EvidenceView evidence={meta?.i18n?.[lang]} developerMode={developerMode} documentNames={documentNames} /></div>)}
          </dd></div>;
        })}</dl>{developerMode && <details className="recordDeveloper"><summary>Geliştirici: Ham JSON</summary><pre>{JSON.stringify(selectedRecord, null, 2)}</pre></details>}</section>
      </>}
    </>}
  </div></>;
}
