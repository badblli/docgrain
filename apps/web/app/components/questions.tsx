import { useEffect, useState } from "react";
import { Head, Icon } from "./console-ui";
import { QuestionCard } from "./question-card";
import { ReviewNotice, ReviewState } from "./review-states";
import type { WorkspaceReview } from "./workspace-review";

export function QuestionsView({ review, focusedId, onCollections, readOnly = false }: {
  review: WorkspaceReview; focusedId?: string; onCollections: () => void; readOnly?: boolean;
}) {
  const [filter, setFilter] = useState("");
  const focused = review.questions.find(item => item.id === focusedId);
  useEffect(() => { if (focused) setFilter(focused.collection); }, [focusedId, focused?.collection]);
  const labels = new Map(review.summary?.collections.map(item => [item.key, item.label]) ?? []);
  review.questions.forEach(item => labels.set(item.collection, item.collection_label));
  const filtered = review.questions.filter(item => !filter || item.collection === filter);
  const question = focused && filtered.some(item => item.id === focused.id) && !review.deferred.includes(focused.id) ? focused : filtered.find(item => !review.deferred.includes(item.id));
  const denominator = review.total + review.answered;
  return <><Head title="Sorular" sub="Kaynakların farklı söylediği bilgileri birlikte netleştirelim." endpoint="" />
    <div className="wrap questionsWrap">
      <div className="questionToolbar"><div className="questionProgress"><span>{review.questionState === "ready" ? `${review.total} soru cevap bekliyor · ${review.answered} cevap kaydedildi` : "Sorular hazırlanıyor…"}</span><progress aria-label="Cevaplanan sorular" max={denominator || 1} value={review.answered} /></div>
        <label className="collectionFilter">Koleksiyon<select value={filter} disabled={review.busy || review.questionState !== "ready"} onChange={event => setFilter(event.target.value)}><option value="">Tüm koleksiyonlar</option>{Array.from(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      </div>
      <ReviewNotice notice={review.notice} />
      {readOnly && <p className="collectionWarning">Örnek görünümde cevaplar kaydedilemez.</p>}
      {review.questionState !== "ready" ? <ReviewState state={review.questionState} subject="Sorular" retry={() => void review.reload()} /> : question ? <QuestionCard key={question.id} question={question} focusOnEnter={Boolean(focusedId) || review.answered > 0 || review.deferred.length > 0} totalCount={denominator} currentIndex={review.answered + 1} busy={review.busy} readOnly={readOnly} onAnswer={body => review.answer(question, body)} /> : <div className="card statePanel">
        <Icon name={filtered.length ? "clock" : "check"} />
        <h2>{filtered.length ? "Bu soruları sonraya bıraktınız" : review.total === 0 ? "Bütün sorular cevaplandı" : "Bu koleksiyonda açık soru yok"}</h2>
        <p>{filtered.length ? "Hazır olduğunuzda kaldığınız yerden devam edin." : "Koleksiyonlarınızı ve kaynaklarını inceleyebilirsiniz."}</p>
        {filtered.length ? <button className="btn" onClick={review.revisit}>Soruları yeniden göster</button> : <button className="btn" onClick={onCollections}>Koleksiyonlara git</button>}
      </div>}
    </div>
  </>;
}
