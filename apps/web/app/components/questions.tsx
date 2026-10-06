import { useEffect, useState } from "react";
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
  const labels = new Map(review.summary?.collections.map(item => [item.key, item.label]) ?? []);
  all.forEach(item => labels.set(item.collection, item.collection_label));
  const filtered = all.filter(item => !filter || item.collection === filter);
  const pending = filtered.filter(item => !completed.some(done => done.id === item.id));
  const question = filtered.find(item => item.id === selectedId) ??
    (focused && !review.deferred.includes(focused.id) && pending.some(item => item.id === focused.id) ? focused : pending.find(item => !review.deferred.includes(item.id)));
  const done = completed.some(item => item.id === question?.id);
  const denominator = review.total + review.answered;
  return <><Head title="Sorular" sub="Belgeleriniz bazı konularda farklı şeyler söylüyor. Doğru olanı seçin; koleksiyonlarınız buna göre güncellenir." endpoint="" />
    <div className="wrap questionsWrap">
      <div className="questionToolbar"><div className="questionProgress"><span>{review.questionState === "ready" ? `${denominator} sorudan ${review.answered}'i cevaplandı` : "Sorular hazırlanıyor…"}</span><progress aria-label="Cevaplanan sorular" max={denominator || 1} value={review.answered} /></div>
        <label className="collectionFilter">Koleksiyon<select value={filter} disabled={review.busy || review.questionState !== "ready"} onChange={event => { setFilter(event.target.value); setSelectedId(undefined); }}><option value="">Tümü</option>{Array.from(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      </div>
      {!question && <ReviewNotice notice={review.notice} />}
      {readOnly && <p className="collectionWarning">Örnek görünümde cevaplar kaydedilemez.</p>}
      {review.questionState !== "ready" ? <><ReviewNotice notice={review.notice} /><ReviewState state={review.questionState} subject="Sorular" retry={() => void review.reload()} /></> : <div className="questionsLayout">
        {filtered.length > 0 && <ul className="questionList" aria-label="Soru listesi">{filtered.map(item => {
          const state = completed.some(done => done.id === item.id) ? "done" : review.deferred.includes(item.id) ? "later" : "open";
          return <li key={item.id}><button className="questionListItem" disabled={review.busy} aria-current={question?.id === item.id ? "true" : undefined} onClick={() => setSelectedId(item.id)}>
            <span className={`questionStateDot ${state}`} role="img" aria-label={state === "done" ? "Cevaplandı" : state === "later" ? "Sonraya bırakıldı" : "Cevap bekliyor"}>{state === "done" && <Icon name="check" />}</span>
            <span>{item.record_title} · {item.field_label}<small>{item.collection_label}{state === "later" ? " · sonraya bırakıldı" : state === "done" ? " · Onaylandı" : ""}</small></span>
          </button></li>;
        })}</ul>}
        {question ? <QuestionCard key={question.id} question={question} focusOnEnter={Boolean(focusedId) || review.answered > 0 || review.deferred.length > 0} totalCount={denominator} currentIndex={all.findIndex(item => item.id === question.id) + 1} busy={review.busy} readOnly={readOnly || done} notice={done ? "Kaydedildi" : review.notice} savedAnswer={review.questionAnswers?.[question.id]} onAnswer={async body => {
          const saved = await review.answer(question, body);
          if (saved) setSelectedId(undefined);
          return saved;
        }} /> : <div className={`card statePanel ${pending.length || review.total > 0 ? "" : "completeState"}`}>
          <Icon name={pending.length ? "clock" : "check"} />
          <h2>{pending.length ? "Bu soruları sonraya bıraktınız" : review.total === 0 ? "Bütün sorular cevaplandı" : "Bu koleksiyonda açık soru yok"}</h2>
          <p>{pending.length ? "Hazır olduğunuzda listeden bir soru seçin veya kaldığınız yerden devam edin." : "Koleksiyonlarınızı ve kaynaklarını inceleyebilirsiniz."}</p>
          {pending.length ? <button className="btn" onClick={review.revisit}>Soruları yeniden göster</button> : <button className="btn" onClick={onCollections}>Koleksiyonlara git</button>}
        </div>}
      </div>}
    </div>
  </>;
}
