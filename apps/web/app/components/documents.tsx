import { RecordJobProgress, type RecordJob } from "./record-job-progress";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDeveloperMode } from "./developer-mode";
import { ACCEPTED_FILE_TYPES, UPLOAD_SUMMARY } from "@/lib/source-formats";
import { Head, Icon, Ep, pageBody } from "./console-ui";
import type { DocumentRow, UploadState, Mode } from "./console-types";

type ReadingReport = {
  summary: string; low_confidence_pages: number[]; image_only_pages: number[];
  images_not_understood: number; unresolved_regions: number; column_table_conflicts: number;
  model_enabled: boolean;
  pages: { page_number: number; codes: string[]; state: string; model_reading: { model: string } | null;
    picture_state?: string | null; picture_reading?: { model: string } | null }[];
};
const READING_API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const readingStates: Record<string, string> = {
  read_local: "Okundu", waiting_model: "Model bekliyor", budget_deferred: "Sonraki okumayı bekliyor",
  model_failed: "Model yeniden denemeli", image_unavailable: "Sayfa görseli hazırlanmalı", needs_review: "İnceleme bekliyor",
};
const pictureStates: Record<string, string> = {
  waiting_model: "görseller model bekliyor", budget_deferred: "görseller sonraki okumayı bekliyor",
  model_failed: "görseller yeniden denenmeli", image_unavailable: "görseller hazırlanmalı", needs_review: "görseller inceleme bekliyor",
};
function ReadingQuality({ document, mode, developerMode }: { document: DocumentRow; mode: Mode | null; developerMode: boolean }) {
  const [report, setReport] = useState<ReadingReport | null>(null);
  const [message, setMessage] = useState("Okuma raporu hazırlanıyor.");
  useEffect(() => {
    setReport(null);
    if (mode !== "live" || !document.versionId) { setMessage("Okuma raporu henüz yok."); return; }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const response = await fetch(`${READING_API}/v1/documents/${encodeURIComponent(document.id)}/versions/${encodeURIComponent(document.versionId!)}/reading-quality`, { signal: controller.signal, cache: "no-store" });
        if (controller.signal.aborted) return;
        if (response.ok) {
          const data: ReadingReport = await response.json();
          if (!controller.signal.aborted) setReport(data);
        } else setMessage(response.status === 404 ? "Okuma raporu henüz yok." : "Okuma raporu alınamadı.");
      } catch { if (!controller.signal.aborted) setMessage("Okuma raporu alınamadı."); }
      if (!controller.signal.aborted && ["running", "processing", "queued", "pending"].includes(document.status)) timer = setTimeout(load, 3000);
    };
    void load();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [document.id, document.versionId, document.status, mode]);
  if (!report) return <p className="mt-2 text-2xs font-normal text-muted">{message}</p>;
  return <details className="relative mt-2 text-2xs font-normal" onClick={event => event.stopPropagation()}>
    <summary className="cursor-pointer whitespace-normal wrap-anywhere text-muted" aria-label={`${document.title}: okuma ayrıntıları`}>{report.summary}</summary>
    <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-line bg-paper p-3 shadow-sm sm:absolute sm:z-10 sm:w-72" role="region" aria-label="Okuma ayrıntıları">
      <p className="mb-2 text-muted">Okuma durumu bilgilerin doğruluğunu veya onaylandığını göstermez. Modelin okuduğu sayfaları kaynakla kontrol edin.</p>
      {!report.model_enabled && report.pages.some(page => page.state !== "read_local" || page.picture_state === "waiting_model") && <p className="mb-2 text-muted">Model kapalı: bu sayfalar bilgisayar dışına gönderilmedi. Ayarlar'dan model açılınca okunur.</p>}
      <ul className="grid list-none gap-1 p-0">
        <li>Zor okunan: {report.low_confidence_pages.length} sayfa</li>
        <li>Yalnızca görsel: {report.image_only_pages.length} sayfa</li>
        <li>Anlaşılamayan görsel: {report.images_not_understood}</li>
        <li>Yeri belirlenemeyen bölüm: {report.unresolved_regions}</li>
        <li>Sütun veya tablo karışıklığı: {report.column_table_conflicts}</li>
        {report.pages.map(page => <li key={page.page_number} className="border-t border-line2 pt-1 wrap-anywhere">{page.page_number}. sayfa: {readingStates[page.state] ?? "Kontrol edilmeli"}{page.picture_state && pictureStates[page.picture_state] ? ` · ${pictureStates[page.picture_state]}` : ""}
          {developerMode && <code className="mt-1 block text-faint">{page.state} · {page.codes.join(", ") || "clean"}{page.model_reading ? ` · ${page.model_reading.model}` : ""}{page.picture_state ? ` · pictures:${page.picture_state}` : ""}</code>}
        </li>)}
      </ul>
    </div>
  </details>;
}

function Status({ status }: { status: string }) {
  const label = status === "done" ? "Hazır" : ["queued", "pending"].includes(status) ? "Sırada" : ["running", "processing"].includes(status) ? "Hazırlanıyor" : status === "failed" ? "Hata" : "Kontrol edilmeli";
  return <Badge variant={status === "done" ? "onay" : ["queued", "pending", "running", "processing"].includes(status) ? "oneri" : "bekliyor"} className="h-auto whitespace-normal">{label}</Badge>;
}
export function Documents({ docs, open, upload, uploadState, uploadStates, retryUpload, extraction, mode }: {
  docs: DocumentRow[]; open: (d: DocumentRow) => void; upload: (files: File[]) => void; uploadState?: UploadState; uploadStates?: UploadState[];
  retryUpload?: (id: string) => void; mode: Mode | null;
  extraction?: { enabled: boolean; reason: string; start: () => void; settings: () => void; job: RecordJob | null; error: string; starting: boolean; showSettings: boolean };
}) {
  const developerMode = useDeveloperMode();
  const input = useRef<HTMLInputElement>(null);
  const busy = mode !== "live";
  const uploads = uploadStates ?? (uploadState && uploadState.phase !== "idle" ? [uploadState] : []);
  return <>
    <Head title="Belgeler" sub="Belgelerinizi yükleyin, durumlarını takip edin ve içeriklerini okuyun." endpoint="GET /v1/documents" />
    <div className={pageBody}>
      <section className="flex flex-wrap items-center gap-4">
        <div className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-paper text-muted"><Icon name="upload" className="size-5" /></div>
        <div className="min-w-0 flex-1"><h3 className="text-base font-semibold">Belgeleri ekleyin</h3>{/* KULLANILMIYOR (karar 18): "PDF, Word, Excel, metin veya görsel dosyalarınızı ekleyin." — WP106: liste Docling biçimlerinden üretiliyor. */}<p className="mt-1 max-w-[56ch] text-xs text-muted">{UPLOAD_SUMMARY} dosyalarınızı ekleyin.</p>

        </div>
        <input ref={input} type="file" multiple hidden accept={ACCEPTED_FILE_TYPES} aria-label={`Dosyaları yükle: ${UPLOAD_SUMMARY}`} disabled={busy} onChange={event => {
          const files = Array.from(event.target.files ?? []); event.target.value = "";
          if (files.length) upload(files);
        }} />
        <Button variant="outline" className="h-auto min-h-[38px] max-w-full whitespace-normal" onClick={() => input.current?.click()} disabled={busy}>{mode === "demo" ? "Örnek görünüm: yükleme kapalı" : mode === null ? "Bağlanıyor…" : busy ? "İşleniyor…" : "Dosya yükle"}</Button>
      </section>
      {uploads.length > 0 && <ul className="grid list-none gap-2 p-0" aria-label="Dosya yükleme durumları">{uploads.map((item, index) => <li key={item.id ?? index} className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-line bg-paper p-3 text-xs" role="status">
        <strong className="min-w-0 wrap-anywhere">{item.fileName}</strong><span className={item.phase === "error" || item.phase === "failed" ? "text-danger wrap-anywhere" : "text-muted wrap-anywhere"}>{item.message}</span>
        {item.phase === "error" && item.id && retryUpload && <Button variant="outline" size="sm" onClick={() => retryUpload(item.id!)} disabled={busy} aria-label={`${item.fileName}: yeniden yükle`}>Yeniden dene</Button>}
        {developerMode && item.jobId && <code className="wrap-anywhere text-faint">{item.jobId}</code>}
      </li>)}</ul>}
      {extraction && <section className="grid gap-4 rounded-card border border-line bg-paper p-4 sm:p-5" aria-labelledby="extract-title">
        <div><h2 id="extract-title" className="text-base font-semibold">Belgelerden bilgilerinizi derleyin</h2><p className="mt-1 max-w-[72ch] text-sm text-muted">Belgenin hazır olması, bilgilerinin çıkarıldığı veya onaylandığı anlamına gelmez. Bilgi çıkarıldıktan sonra kaynakları kontrol edip Sorular'da onaylayın.</p></div>
        {extraction.reason && <p className="max-w-[72ch] text-sm text-muted" role="status">{extraction.reason}</p>}
        <div className="flex flex-wrap gap-2"><Button className="h-auto min-h-[38px] max-w-full whitespace-normal" disabled={!extraction.enabled} onClick={extraction.start}>{extraction.starting ? "Başlatılıyor…" : "Bilgileri çıkar"}</Button>
          {extraction.showSettings && <Button variant="outline" onClick={extraction.settings}>Ayarlar'a git</Button>}</div>
        <RecordJobProgress job={extraction.job} error={extraction.error} />
      </section>}
      <Card className="gap-0 border border-line p-0 ring-0">
        <CardHeader className="flex flex-wrap items-center gap-2 border-b border-line2 px-5 py-4"><CardTitle className="text-sm font-semibold">Tüm belgeler</CardTitle><CardDescription className="text-2xs">İçeriğini okumak için bir belge açın.</CardDescription><span className="ml-auto"><Ep>GET /v1/documents?limit=50</Ep></span></CardHeader>
        <Table className="w-full table-fixed text-xs [&_td]:p-2 sm:[&_td]:p-4 [&_th]:p-2 sm:[&_th]:p-4">
          <TableHeader className="bg-sheet"><TableRow><TableHead className="w-[55%] sm:w-[37%]">Belge</TableHead><TableHead>Durum</TableHead><TableHead className="hidden sm:table-cell">Sürüm</TableHead><TableHead className="hidden sm:table-cell">Sayfa</TableHead><TableHead className="hidden sm:table-cell">Son işlem</TableHead><TableHead className="w-[60px] sm:w-[74px]"><span className="sr-only">İşlem</span></TableHead></TableRow></TableHeader>
          <TableBody>{!docs.length && <TableRow><TableCell colSpan={6}>Henüz belge yok.</TableCell></TableRow>}{docs.map(d => <TableRow key={d.id} className="cursor-pointer" onClick={() => open(d)}>
            <TableCell><span className="flex items-center gap-2 font-semibold whitespace-normal wrap-anywhere"><span className="hidden rounded-xs bg-line2 font-mono text-2xs font-bold text-ink2 sm:inline p-1">{d.type}</span><span className="min-w-0">{d.title}<small className="mt-1 hidden font-mono text-2xs font-normal text-faint sm:block">{d.file}{developerMode ? ` · ${d.id}` : ""}</small></span></span></TableCell>
            <TableCell><Status status={d.status} /><ReadingQuality document={d} mode={mode} developerMode={developerMode} /></TableCell><TableCell className="hidden sm:table-cell">{d.version}</TableCell><TableCell className="hidden sm:table-cell">{d.pages || "—"}</TableCell><TableCell className="hidden font-mono text-muted sm:table-cell">{d.updated}</TableCell>
            <TableCell><Button variant="outline" size="sm" aria-label={`${d.title} belgesini aç`} onClick={e => { e.stopPropagation(); open(d); }}>Aç</Button></TableCell>
          </TableRow>)}</TableBody>
        </Table>
      </Card>
    </div>
  </>;
}
