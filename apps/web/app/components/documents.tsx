import { useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDeveloperMode } from "./developer-mode";
import { Head, Icon, Ep } from "./console-ui";
import type { DocumentRow, UploadState, Mode } from "./console-types";

function Status({ status }: { status: string }) {
  const label = status === "done" ? "Hazır" : ["queued", "pending"].includes(status) ? "Sırada" : ["running", "processing"].includes(status) ? "Hazırlanıyor" : "Kontrol edilmeli";
  return <Badge variant={status === "done" ? "onay" : ["queued", "pending", "running", "processing"].includes(status) ? "oneri" : "bekliyor"} className="h-auto whitespace-normal">{label}</Badge>;
}
export function Documents({ docs, open, upload, uploadState, mode }: {
  docs: DocumentRow[]; open: (d: DocumentRow) => void; upload: (file: File) => Promise<void>; uploadState: UploadState; mode: Mode | null;
}) {
  const developerMode = useDeveloperMode();
  const input = useRef<HTMLInputElement>(null);
  const busy = mode !== "live" || ["registering", "uploading", "confirming", "queued", "running"].includes(uploadState.phase);
  return <>
    <Head title="Belgeler" sub="Belgelerinizi yükleyin, durumlarını takip edin ve içeriklerini okuyun." endpoint="GET /v1/documents" />
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-4 pb-16 pt-6 md:gap-8 md:px-6 xl:px-10">
      <section className="flex flex-wrap items-center gap-4">
        <div className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-paper text-muted"><Icon name="upload" className="size-5" /></div>
        <div className="min-w-0 flex-1"><h3 className="text-base font-semibold">Yeni bir belge ekleyin</h3><p className="mt-1 max-w-[56ch] text-xs text-muted">PDF, Word, Excel, metin veya görsel dosyalarınızı ekleyin.</p>
          {uploadState.phase !== "idle" && <div className="mt-2 flex flex-wrap items-center gap-2 text-2xs text-muted wrap-anywhere" role="status">
            <span className={`size-2 rounded-full ${uploadState.phase === "done" ? "bg-ok" : ["partial", "failed", "error"].includes(uploadState.phase) ? "bg-danger" : "bg-muted"}`} aria-hidden="true" />
            <b className="text-ink2">{uploadState.fileName}</b><span>{developerMode || uploadState.phase !== "error" ? uploadState.message : "Dosya yüklenemedi. Bağlantıyı kontrol edip yeniden deneyin."}</span>{developerMode && uploadState.jobId && <code className="font-mono text-faint">{uploadState.jobId}</code>}
          </div>}
        </div>
        <input ref={input} type="file" hidden accept=".pdf,.docx,.xlsx,.txt,.png,.jpg,.jpeg" aria-label="Dosya yükle: PDF, DOCX, XLSX, TXT, PNG, JPG veya JPEG" disabled={busy} onChange={event => {
          const file = event.target.files?.[0]; if (!file) return;
          void upload(file).finally(() => { if (input.current) input.current.value = ""; });
        }} />
        <Button variant="outline" className="h-auto min-h-[38px] max-w-full whitespace-normal" onClick={() => input.current?.click()} disabled={busy}>{mode === "demo" ? "Örnek görünüm: yükleme kapalı" : mode === null ? "Bağlanıyor…" : busy ? "İşleniyor…" : "Dosya yükle"}</Button>
      </section>
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
