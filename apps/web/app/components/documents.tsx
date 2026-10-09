import { RecordJobProgress, type RecordJob } from "./record-job-progress";
import { useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDeveloperMode } from "./developer-mode";
import { ACCEPTED_FILE_TYPES, UPLOAD_SUMMARY } from "@/lib/source-formats";
import { Head, Icon, Ep, pageBody } from "./console-ui";
import type { DocumentRow, UploadState, Mode } from "./console-types";

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
            <TableCell><Status status={d.status} /></TableCell><TableCell className="hidden sm:table-cell">{d.version}</TableCell><TableCell className="hidden sm:table-cell">{d.pages || "—"}</TableCell><TableCell className="hidden font-mono text-muted sm:table-cell">{d.updated}</TableCell>
            <TableCell><Button variant="outline" size="sm" aria-label={`${d.title} belgesini aç`} onClick={e => { e.stopPropagation(); open(d); }}>Aç</Button></TableCell>
          </TableRow>)}</TableBody>
        </Table>
      </Card>
    </div>
  </>;
}
