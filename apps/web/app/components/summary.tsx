import { Ep, Icon } from "./console-ui";
import { CollectionCard } from "./collection-card";
import { QuestionCard } from "./question-card";
import { ReviewNotice, ReviewState } from "./review-states";
import type { WorkspaceReview } from "./workspace-review";

export function SummaryView({ companyName, review, onCollections, onQuestions, onDocuments, readOnly = false }: {
  companyName: string; review: WorkspaceReview; onCollections: (key?: string) => void;
  onQuestions: () => void; onDocuments: () => void; readOnly?: boolean;
}) {
  const { summary, summaryState } = review;
  const question = review.questions.find(item => !review.deferred.includes(item.id));
  const updated = summary?.updated_at ? new Date(summary.updated_at) : null;
  return <div className="wrap overviewWrap">
    <header className="summaryHeader"><span className="eyebrow">Şirket özeti</span><h1>{companyName}</h1><p className="sub">{summary ? `${summary.documents} belgeden derlendi · son güncelleme ${updated && !Number.isNaN(updated.getTime()) ? updated.toLocaleString("tr-TR", { dateStyle: "long", timeStyle: "short" }) : "henüz yok"}` : "Belgelerinizden derlenen bilgilerin tümü bir arada."}</p></header>
    {summaryState !== "ready" ? <ReviewState state={summaryState} subject="Özet" retry={() => void review.reload()} /> : summary && <>
      <div className="summaryMetrics" aria-label="Şirket bilgileri">
        <div className="metricTile"><span>Kayıt</span><strong>{summary.records.toLocaleString("tr-TR")}</strong><small>Koleksiyonlarınızda</small></div>
        <div className={`metricTile ${summary.unsupported_fields === 0 ? "approvedText" : ""}`}><span>Kaynaksız bilgi</span><strong>{summary.unsupported_fields}</strong><small>{summary.unsupported_fields === 0 ? "Her bilginin kaynağı var" : "Kaynağı kontrol edilmeli"}</small></div>
        <div className={`metricTile ${summary.conflicts > 0 ? "conflictText" : ""}`}><span>Çelişki</span><strong>{summary.conflicts}</strong><small>Kaynaklar farklı söylüyor</small></div>
        <div className="metricTile"><span>Onaylı</span><strong>{Math.round(Math.max(0, Math.min(1, summary.accepted_ratio)) * 100)}<span className="metricUnit">%</span></strong><meter className="approvalMeter" min={0} max={1} value={summary.accepted_ratio} aria-label="Onaylı bilgi oranı" /><small>Kontrol edilen bilgiler</small></div>
      </div>
      {summary.documents === 0 && <div className="card statePanel"><Icon name="doc" /><h2>Şirketinizin hikâyesi belgelerinizle başlar</h2><p>İlk belgenizi ekleyin; derlenen bilgiler burada bir araya gelsin.</p><button className="btn" onClick={onDocuments}>Belgelere git</button></div>}
    </>}
    <section className="summaryQuestions" aria-labelledby="waiting-title">
      <div className="sectionHeading"><h2 id="waiting-title">Sizden bir cevap bekliyor</h2><button className="textButton" onClick={onQuestions}>Tüm sorular <Icon name="arrow" /></button></div>
      {(!question || review.questionState !== "ready") && <ReviewNotice notice={review.notice} />}
      {readOnly && <p className="collectionWarning">Örnek görünümde cevaplar kaydedilemez.</p>}
      {review.questionState !== "ready" ? <ReviewState state={review.questionState} subject="Sorular" retry={() => void review.reload()} /> : question ? <QuestionCard key={question.id} question={question} focusOnEnter={review.answered > 0 || review.deferred.length > 0} totalCount={review.total + review.answered} currentIndex={review.answered + 1} busy={review.busy} readOnly={readOnly} notice={review.notice} onAnswer={body => review.answer(question, body)} /> : <div className={`card quietState ${review.total === 0 ? "completeState" : ""}`}><Icon name="check" /><div><h3>{review.total > 0 ? "Soruları sonraya bıraktınız" : "Bütün sorular cevaplandı"}</h3><p>{review.total > 0 ? "Hazır olduğunuzda Sorular bölümünden devam edebilirsiniz." : "Şu anda sizden cevap bekleyen bir soru yok."}</p></div></div>}
    </section>
    {summary && <section aria-labelledby="summary-collections-title"><div className="sectionHeading"><h2 id="summary-collections-title">Koleksiyonlar</h2><button className="textButton" onClick={() => onCollections()}>Tümünü gör <Icon name="arrow" /></button></div>
      {summary.collections.length ? <div className="collectionGrid">{summary.collections.map(collection => <CollectionCard key={collection.key} collection={collection} onOpen={() => onCollections(collection.key)} />)}</div> : <div className="card quietState"><Icon name="grid" /><div><h3>Henüz koleksiyon yok</h3><p>Belgelerinizden derlenen kayıtlar burada görünecek.</p></div></div>}
    </section>}
    <Ep>GET /v1/workspaces/{summary?.workspace_id ?? "…"}/summary</Ep>
  </div>;
}
