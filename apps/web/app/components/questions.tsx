import { useEffect, useState } from "react";
import { displayCollectionLabel, getFieldLabel } from "./information/labels";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { Head, Icon } from "./console-ui";
import { QuestionCard } from "./question-card";
import { ReviewNotice, ReviewState } from "./review-states";
import type { WorkspaceReview } from "./workspace-review";

export function QuestionsView({ review, focusedId, onCollections, readOnly = false }: {
  review: WorkspaceReview; focusedId?: string; onCollections: () => void; readOnly?: boolean;
}) {
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string>();
  const focused = review.questions.find(item => item.id === focusedId);
  useEffect(() => { if (focused) { setFilter(focused.collection); setSelectedId(focused.id); } }, [focusedId, focused?.collection]);
  const completed = review.answeredQuestions ?? [];
  const all = [...review.questions, ...completed];
  if (review.questionOrder) all.sort((a, b) => review.questionOrder.indexOf(a.id) - review.questionOrder.indexOf(b.id));
  const labels = new Map(review.summary?.collections.map(item => [item.key, displayCollectionLabel(item.key, item.label)]) ?? []);
  all.forEach(item => labels.set(item.collection, displayCollectionLabel(item.collection, item.collection_label)));
  const filtered = all.filter(item => !filter || item.collection === filter);
  const pending = filtered.filter(item => !completed.some(done => done.id === item.id));
  const question = filtered.find(item => item.id === selectedId) ??
    (focused && !review.deferred.includes(focused.id) && pending.some(item => item.id === focused.id) ? focused : pending.find(item => !review.deferred.includes(item.id)));
  const done = completed.some(item => item.id === question?.id);
  const denominator = review.total + review.answered;
  return <><Head title="Sorular" sub="Belgeleriniz bazı konularda farklı şeyler söylüyor. Doğru olanı seçin; koleksiyonlarınız buna göre güncellenir." endpoint="" />
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-4 pb-16 pt-6 md:gap-8 md:px-6 xl:px-10">
      <div className="flex flex-wrap items-end justify-between gap-4 md:gap-8">
        <div className="min-w-[180px] flex-1 text-sm text-muted"><span>{review.questionState === "ready" ? `${denominator} sorudan ${review.answered}'i cevaplandı` : "Sorular hazırlanıyor…"}</span><Progress aria-label="Cevaplanan sorular" value={denominator ? review.answered / denominator * 100 : 0} className="mt-3 h-1 bg-sunken [&_[data-slot=progress-indicator]]:bg-ok" /></div>
        <div className="grid w-full gap-2 sm:w-auto"><Label htmlFor="collection-filter" className="text-xs font-normal text-muted">Koleksiyon</Label>
          <Select value={filter || "__all__"} disabled={review.busy || review.questionState !== "ready"} onValueChange={value => { setFilter(value === "__all__" ? "" : value); setSelectedId(undefined); }}>
            <SelectTrigger id="collection-filter" className="h-[38px] w-full bg-paper sm:min-w-44"><SelectValue>{filter ? labels.get(filter) : "Tümü"}</SelectValue></SelectTrigger>
            <SelectContent><SelectItem value="__all__">Tümü</SelectItem>{Array.from(labels).map(([key, label]) => <SelectItem key={key} value={key}>{label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      </div>
      {!question && <ReviewNotice notice={review.notice} />}
      {readOnly && <p className="text-xs text-muted">Örnek görünümde cevaplar kaydedilemez.</p>}
      {review.questionState !== "ready" ? <><ReviewNotice notice={review.notice} /><ReviewState state={review.questionState} subject="Sorular" retry={() => void review.reload()} /></> : <div className={cn("grid min-w-0 items-start gap-4 xl:gap-6", filtered.length > 0 && "md:grid-cols-[180px_minmax(0,1fr)] xl:grid-cols-[220px_minmax(0,1fr)]")}>
        {filtered.length > 0 && <ScrollArea className="h-[220px] min-w-0 md:h-[min(70vh,800px)]"><ul className="m-0 grid list-none gap-1 p-0" aria-label="Soru listesi">{filtered.map(item => {
          const state = completed.some(done => done.id === item.id) ? "done" : review.deferred.includes(item.id) ? "later" : "open";
          return <li key={item.id}><Button variant="ghost" className="h-auto w-full items-start justify-start gap-2 rounded-lg border border-transparent text-left text-sm whitespace-normal aria-[current=true]:border-accent-line aria-[current=true]:bg-accent-soft p-3" disabled={review.busy} aria-current={question?.id === item.id ? "true" : undefined} onClick={() => setSelectedId(item.id)}>
            <span className={cn("mt-1 size-2 shrink-0 rounded-full bg-warn", state === "later" && "border border-faint bg-transparent", state === "done" && "size-3.5 bg-ok-soft text-ok")} role="img" aria-label={state === "done" ? "Cevaplandı" : state === "later" ? "Sonraya bırakıldı" : "Cevap bekliyor"}>{state === "done" && <Icon name="check" className="size-3.5" />}</span>
            <span className="min-w-0 wrap-anywhere">{item.record_title} · {getFieldLabel(item.field, item.field_label)}<small className="mt-1 block text-2xs font-normal text-muted">{displayCollectionLabel(item.collection, item.collection_label)}{state === "later" ? " · sonraya bırakıldı" : state === "done" ? " · Onaylandı" : ""}</small></span>
          </Button></li>;
        })}</ul></ScrollArea>}
        {question ? <QuestionCard key={question.id} question={question} focusOnEnter={Boolean(focusedId) || review.answered > 0 || review.deferred.length > 0} totalCount={denominator} currentIndex={all.findIndex(item => item.id === question.id) + 1} busy={review.busy} readOnly={readOnly || done} notice={done ? "Kaydedildi" : review.notice} savedAnswer={review.questionAnswers?.[question.id]} onAnswer={async body => {
          const saved = await review.answer(question, body);
          if (saved) setSelectedId(undefined);
          return saved;
        }} /> : <Card className="items-center gap-3 border border-dashed border-line-strong px-6 py-10 text-center ring-0">
          <Icon name={pending.length ? "clock" : "check"} className={cn("size-9 rounded-full bg-sheet p-2 text-muted", !pending.length && review.total === 0 && "bg-ok-soft text-ok")} />
          <h2 className="text-md font-semibold">{pending.length ? "Bu soruları sonraya bıraktınız" : review.total === 0 ? "Bütün sorular cevaplandı" : "Bu koleksiyonda açık soru yok"}</h2>
          <p className="mb-2 max-w-[48ch] text-sm text-muted">{pending.length ? "Hazır olduğunuzda listeden bir soru seçin veya kaldığınız yerden devam edin." : "Koleksiyonlarınızı ve kaynaklarını inceleyebilirsiniz."}</p>
          {pending.length ? <Button variant="outline" onClick={review.revisit}>Soruları yeniden göster</Button> : <Button variant="outline" onClick={onCollections}>Koleksiyonlara git</Button>}
        </Card>}
      </div>}
    </div>
  </>;
}
