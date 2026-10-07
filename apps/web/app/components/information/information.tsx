"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ReviewBadge } from "../review-states";


import { useEffect, useState } from "react";
import { useDeveloperMode } from "../developer-mode";
import { Head, Ep, Icon } from "../console-ui";
import { CollectionCard } from "../collection-card";
import { displayCollectionLabel, getFieldLabel } from "./labels";
import { SourceQuote, type Question } from "../question-card";
import type { CollectionSummary, LoadState } from "../workspace-review";

type Evidence = { document_id: string; document_name?: string; locator: string; quote: string };
type FieldMeta = {
  lang?: string; review_state?: string; evidence?: Evidence[];
  schedule?: { label_tr: string };
  i18n?: Record<string, Evidence[]>; i18n_review_state?: Record<string, string>;
};
type RecordRow = {
  id: string; _meta?: { identity?: string; review_state?: string; fields?: Record<string, FieldMeta>; conflicts?: { field: string; lang: string }[] };
  i18n?: Record<string, Record<string, unknown>>; [field: string]: unknown;
};
type CollectionResult = { rows: RecordRow[]; failed: boolean };
const visibleFields = (row: RecordRow) => Object.keys(row).filter(key => !["id", "_meta", "i18n"].includes(key));
function recordTitle(row: RecordRow) {
  if (row._meta?.identity) return valueText(row[row._meta.identity]);
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

function EvidenceView({ evidence, developerMode, documentNames, value }: { evidence?: Evidence[]; developerMode: boolean; documentNames: Record<string, string>; value: unknown }) {
  if (!evidence?.length) return null;
  return <details className="[&_blockquote]:font-serif [&_blockquote]:text-md [&_blockquote]:leading-[var(--leading-doc)] [&_blockquote]:text-ink2 [&_blockquote]:mt-2 [&_blockquote]:mb-1 [&_blockquote]:wrap-anywhere text-xs text-muted mt-3 [&_summary]:cursor-pointer [&_summary]:text-accent [&_ul]:pl-5 [&_li_+_li]:mt-4 [&_blockquote]:mx-0"><summary>Kaynakta göster</summary><ul>{evidence.map((item, index) => <li key={index}>
    <span>{item.document_name || documentNames[item.document_id] || (developerMode ? item.document_id : `Kaynak belge ${index + 1}`)}</span>
    <SourceQuote quote={item.quote ?? ""} values={[value]} />
    {item.locator && <span className="font-normal font-mono text-faint mt-1 mb-0 wrap-anywhere block mx-0">{item.locator}</span>}
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

  const labelFor = (key: string) => displayCollectionLabel(key, summaries.find(item => item.key === key)?.label);
  const questionFor = (field: string, lang?: string) => questions.find(item => item.collection === selectedCollection && (item.record_id === selectedRecord?.id || item.record_ids?.includes(selectedRecord?.id ?? "")) && item.field === field && (!lang || item.lang === lang));
  const questionButton = (question?: Question) => question && <Button variant="ghost" className="inline-flex align-[middle] border-0 bg-transparent rounded-sm [&:hover]:bg-warn-soft p-1" onClick={() => onQuestion(question)} aria-label={`${question.field_label}: açık soruyu cevapla`} title="Bu bilgi için bir soru var"><span className="inline-block w-[6px] h-[6px] rounded-pill bg-warn flex-none" aria-hidden="true" /></Button>;
  const retry = () => setRefreshKey(value => value + 1);
  const result = results[selectedCollection];

  return <><Head title="Koleksiyonlar" sub="Belgelerinizden derlenen kayıtları ve kaynaklarını inceleyin." endpoint={revision ? `GET /v1/workspaces/${workspaceId}/revisions/${revision}/collections` : ""}>
    <Label className="flex items-center gap-2 text-xs font-normal text-muted"><input className="size-4 accent-accent" type="checkbox" role="switch" checked={mode === "approved"} onChange={event => { setMode(event.target.checked ? "approved" : "preview"); setSelectedCollection(""); }} />Yalnızca onaylı bilgiler</Label>
  </Head><div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-4 pb-16 pt-6 md:gap-8 md:px-6 xl:px-10">
    {state === "loading" ? <InformationState role="status"><Skeleton className="mx-auto h-1 w-12 bg-accent" /><h2>Koleksiyonlar hazırlanıyor…</h2><p>Şirketinizin kayıtları alınıyor.</p></InformationState> : state !== "ready" ? <InformationState role={state === "error" ? "alert" : "status"}><Icon name="grid" /><h2>{state === "missing" ? "Koleksiyonlar henüz hazır değil" : "Koleksiyonlar alınamadı"}</h2><p>Biraz sonra tekrar deneyebilirsiniz.</p><Button variant="outline" onClick={retry}>Tekrar dene</Button></InformationState> : !collections.length ? <InformationState><Icon name="grid" /><h2>Henüz koleksiyon yok</h2><p>Belgelerinizden derlenen kayıtlar burada görünecek.</p></InformationState> : !selectedCollection ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{collections.map(key => {
      const data = results[key];
      const summary = summaries.find(item => item.key === key);
      const collection = summary ?? { key, label: labelFor(key), records: data?.rows.length ?? 0, conflicts: data?.rows.reduce((sum, row) => sum + (row._meta?.conflicts?.length ?? 0), 0) ?? 0, needs_review: data?.rows.filter(row => row._meta?.review_state !== "accepted").length ?? 0 };
      return !summary && !data ? <Card className="gap-2 border border-line p-5 ring-0" key={key} role="status"><Icon name="grid" /><h3 className="text-md font-semibold">{labelFor(key)}</h3><p className="text-sm text-muted">Kayıtlar yükleniyor…</p></Card> : !summary && data?.failed ? <Card className="gap-2 border border-line p-5 ring-0" key={key} role="alert"><h3 className="text-md font-semibold">{labelFor(key)}</h3><p className="text-sm text-muted">Kayıtlar alınamadı.</p><Button variant="ghost" className="self-start" onClick={retry}>Tekrar dene</Button></Card> : <CollectionCard key={key} collection={collection} onOpen={() => { setSelectedCollection(key); setSelectedRecord(null); }} />;
    })}</div> : <>
      <div className="flex flex-wrap items-center gap-4"><Button variant="outline" className="h-auto max-w-full whitespace-normal" onClick={() => { if (selectedRecord) setSelectedRecord(null); else setSelectedCollection(""); }}>← {selectedRecord ? labelFor(selectedCollection) : "Koleksiyonlar"}</Button><h2 className="text-xl font-semibold wrap-anywhere">{selectedRecord ? recordTitle(selectedRecord) : labelFor(selectedCollection)}</h2>{selectedRecord && <ReviewBadge state={selectedRecord._meta?.review_state} />}</div>
      {questionState === "error" || questionState === "missing" ? <p className="text-xs text-muted">Açık sorular şu anda gösterilemiyor. Sorular bölümünden tekrar deneyebilirsiniz.</p> : null}
      {!result ? <InformationState role="status"><h2>Kayıtlar yükleniyor…</h2></InformationState> : result.failed ? <InformationState role="alert"><h2>Kayıtlar alınamadı</h2><p>Bu koleksiyonun kayıtlarını yeniden yükleyin.</p><Button variant="outline" onClick={retry}>Tekrar dene</Button></InformationState> : !result.rows.length ? <InformationState><h2>Bu koleksiyonda kayıt yok</h2><p>{mode === "approved" ? "Önizlemedeki bilgileri görmek için onaylı bilgi filtresini kapatın." : "Yeni kayıtlar derlendiğinde burada görünecek."}</p></InformationState> : !selectedRecord ? <div className="flex flex-col gap-3">{result.rows.map(row => <Card key={row.id} className="gap-0 border border-line p-0 ring-0 transition-colors hover:border-accent"><button className="flex w-full min-w-0 items-center justify-between gap-4 p-4 text-left sm:px-6 sm:py-5" onClick={() => setSelectedRecord(row)}><span className="min-w-0"><strong className="text-md font-semibold wrap-anywhere">{recordTitle(row)}</strong><ReviewBadge state={row._meta?.review_state} /><span className="mt-2 block text-sm text-muted wrap-anywhere">{recordSummary(row)}</span>{developerMode && <Ep>{row.id}</Ep>}</span><Icon name="arrow" className="size-[18px] shrink-0" /></button></Card>)}</div> : <>
        <div className="flex flex-wrap items-center gap-4"><Label className="flex items-center gap-2 text-xs font-normal text-muted"><input className="size-4 accent-accent" type="checkbox" role="switch" checked={showLanguages} onChange={event => setShowLanguages(event.target.checked)} />Diğer dilleri göster</Label>{questionState === "loading" && <span className="text-xs text-muted" role="status">Açık sorular yükleniyor…</span>}</div>
        <Card className="gap-0 border border-line p-0 ring-0"><dl className="m-0">{visibleFields(selectedRecord).map(field => {
          const meta = selectedRecord._meta?.fields?.[field];
          return <div className="grid grid-cols-1 gap-3 border-b border-line2 p-5 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] sm:gap-6 sm:p-6" key={field}><dt className="min-w-0 text-sm font-semibold wrap-anywhere">{getFieldLabel(field)}{questionButton(questionFor(field))}{developerMode && <div><Ep>{field}</Ep></div>}</dt><dd className="m-0 min-w-0 text-base wrap-anywhere">{valueText(selectedRecord[field])}{meta?.schedule && <p className="mt-1 text-sm text-muted">{meta.schedule.label_tr}</p>}<ReviewBadge state={meta?.review_state} /><EvidenceView value={selectedRecord[field]} evidence={meta?.evidence} developerMode={developerMode} documentNames={documentNames} />
            {showLanguages && Object.entries(selectedRecord.i18n ?? {}).filter(([, fields]) => fields[field] !== undefined).map(([lang, fields]) => <div className="mt-4 rounded-lg bg-sheet p-3 text-sm" key={lang}><span className="mr-2 text-2xs text-muted">{lang}</span>{valueText(fields[field])}<ReviewBadge state={meta?.i18n_review_state?.[lang]} />{questionButton(questionFor(field, lang))}<EvidenceView value={fields[field]} evidence={meta?.i18n?.[lang]} developerMode={developerMode} documentNames={documentNames} /></div>)}
          </dd></div>;
        })}</dl>{developerMode && <details className="m-6"><summary className="cursor-pointer">Geliştirici: Ham JSON</summary><pre className="whitespace-pre-wrap font-mono text-2xs wrap-anywhere">{JSON.stringify(selectedRecord, null, 2)}</pre></details>}</Card>
      </>}
    </>}
  </div></>;
}

function InformationState({ children, role }: { children: React.ReactNode; role?: "status" | "alert" }) {
  return <Card role={role} className="items-center gap-3 border border-dashed border-line-strong px-6 py-10 text-center ring-0 [&_h2]:text-md [&_h2]:font-semibold [&_p]:max-w-[48ch] [&_p]:text-sm [&_p]:text-muted [&>svg]:size-9 [&>svg]:rounded-full [&>svg]:bg-sheet [&>svg]:p-2 [&>svg]:text-muted">{children}</Card>;
}
