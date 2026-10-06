import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Ep, Icon } from "./console-ui";
import { CollectionCard } from "./collection-card";
import { QuestionCard } from "./question-card";
import { ReviewNotice, ReviewState } from "./review-states";
import type { WorkspaceReview } from "./workspace-review";

function Metric({ label, value, detail, color, children }: { label: string; value: React.ReactNode; detail: string; color?: string; children?: React.ReactNode }) {
  return <Card className="min-w-0 gap-0 border border-line p-4 ring-0 xl:p-5">
    <span className="text-sm text-ink2">{label}</span><strong className={`mb-1 mt-2 text-2xl leading-tight font-medium tracking-[-0.035em] tabular-nums sm:text-3xl ${color ?? ""}`}>{value}</strong>
    {children}<small className="text-xs text-muted">{detail}</small>
  </Card>;
}
export function SummaryView({ companyName, review, onCollections, onQuestions, onDocuments, readOnly = false }: {
  companyName: string; review: WorkspaceReview; onCollections: (key?: string) => void;
  onQuestions: () => void; onDocuments: () => void; readOnly?: boolean;
}) {
  const { summary, summaryState } = review;
  const question = review.questions.find(item => !review.deferred.includes(item.id));
  const updated = summary?.updated_at ? new Date(summary.updated_at) : null;
  return <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-4 pb-16 pt-6 md:gap-8 md:px-6 md:pt-10 xl:px-10">
    <header><span className="text-xs text-muted">Şirket özeti</span><h1 className="my-2 text-2xl font-semibold tracking-[-0.035em] wrap-anywhere">{companyName}</h1><p className="text-base text-muted">{summary ? `${summary.documents} belgeden derlendi · son güncelleme ${updated && !Number.isNaN(updated.getTime()) ? updated.toLocaleString("tr-TR", { dateStyle: "long", timeStyle: "short" }) : "henüz yok"}` : "Belgelerinizden derlenen bilgilerin tümü bir arada."}</p></header>
    {summaryState !== "ready" ? <ReviewState state={summaryState} subject="Özet" retry={() => void review.reload()} /> : summary && <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Şirket bilgileri">
        <Metric label="Kayıt" value={summary.records.toLocaleString("tr-TR")} detail="Koleksiyonlarınızda" />
        <Metric label="Kaynaksız bilgi" value={summary.unsupported_fields} color={summary.unsupported_fields === 0 ? "text-ok" : undefined} detail={summary.unsupported_fields === 0 ? "Her bilginin kaynağı var" : "Kaynağı kontrol edilmeli"} />
        <Metric label="Çelişki" value={summary.conflicts} color={summary.conflicts > 0 ? "text-warn" : undefined} detail="Kaynaklar farklı söylüyor" />
        <Metric label="Onaylı" value={<>{Math.round(Math.max(0, Math.min(1, summary.accepted_ratio)) * 100)}<span className="ml-1 text-lg">%</span></>} detail="Kontrol edilen bilgiler"><Progress value={Math.max(0, Math.min(1, summary.accepted_ratio)) * 100} aria-label="Onaylı bilgi oranı" className="my-2 h-1 bg-sunken [&_[data-slot=progress-indicator]]:bg-ok" /></Metric>
      </div>
      {summary.documents === 0 && <Card className="items-center gap-3 border border-dashed border-line-strong px-6 py-10 text-center ring-0"><Icon name="doc" className="size-9 rounded-full bg-sheet p-2 text-muted" /><h2 className="text-md font-semibold">Şirketinizin hikâyesi belgelerinizle başlar</h2><p className="text-sm text-muted">İlk belgenizi ekleyin; derlenen bilgiler burada bir araya gelsin.</p><Button variant="outline" onClick={onDocuments}>Belgelere git</Button></Card>}
    </>}
    <section aria-labelledby="waiting-title">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h2 className="text-md font-semibold sm:text-lg" id="waiting-title">Sizden bir cevap bekliyor</h2><Button variant="ghost" onClick={onQuestions}>Tüm sorular <Icon name="arrow" /></Button></div>
      {(!question || review.questionState !== "ready") && <ReviewNotice notice={review.notice} />}
      {readOnly && <p className="text-xs text-muted">Örnek görünümde cevaplar kaydedilemez.</p>}
      {review.questionState !== "ready" ? <ReviewState state={review.questionState} subject="Sorular" retry={() => void review.reload()} /> : question ? <QuestionCard key={question.id} question={question} focusOnEnter={review.answered > 0 || review.deferred.length > 0} totalCount={review.total + review.answered} currentIndex={review.answered + 1} busy={review.busy} readOnly={readOnly} notice={review.notice} onAnswer={body => review.answer(question, body)} /> : <Card className="flex-row items-center gap-4 border border-line p-6 ring-0"><Icon name="check" className={`size-9 shrink-0 rounded-full p-2 ${review.total === 0 ? "bg-ok-soft text-ok" : "bg-sheet text-muted"}`} /><div><h3 className="text-md font-semibold">{review.total > 0 ? "Soruları sonraya bıraktınız" : "Bütün sorular cevaplandı"}</h3><p className="mt-1 text-sm text-muted">{review.total > 0 ? "Hazır olduğunuzda Sorular bölümünden devam edebilirsiniz." : "Şu anda sizden cevap bekleyen bir soru yok."}</p></div></Card>}
    </section>
    {summary && <section aria-labelledby="summary-collections-title"><div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h2 className="text-md font-semibold sm:text-lg" id="summary-collections-title">Koleksiyonlar</h2><Button variant="ghost" onClick={() => onCollections()}>Tümünü gör <Icon name="arrow" /></Button></div>
      {summary.collections.length ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{summary.collections.map(collection => <CollectionCard key={collection.key} collection={collection} onOpen={() => onCollections(collection.key)} />)}</div> : <Card className="flex-row items-center gap-4 border border-dashed border-line-strong p-6 ring-0"><Icon name="grid" className="size-9 shrink-0 rounded-full bg-sheet p-2 text-muted" /><div><h3 className="text-md font-semibold">Henüz koleksiyon yok</h3><p className="mt-1 text-sm text-muted">Belgelerinizden derlenen kayıtlar burada görünecek.</p></div></Card>}
    </section>}
    <Ep>GET /v1/workspaces/{summary?.workspace_id ?? "…"}/summary</Ep>
  </div>;
}
