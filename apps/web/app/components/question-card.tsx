import { useEffect, useId, useRef, useState } from "react";
import { Icon } from "./console-ui";

export type QuestionOption = {
  candidate_id: string; value: unknown; display: string; quote: string | null;
  document_id: string | null; document_name: string; locator: string | null;
  summary_tr?: string; evidence?: { quote: string; locator: string }[];
};
export type Question = {
  id: string; kind: string; collection: string; collection_label: string;
  record_id: string; record_title: string; field: string; field_label: string;
  lang: string | null; allow_all?: boolean; options: QuestionOption[];
  records?: string[]; record_ids?: string[]; period_label_tr?: string; question_tr?: string;
};
export type QuestionAnswer = { candidate_id: string } | { document_id: string } | { value: unknown; note: string } | { skip: true } | { all: true };
export function groupByDocument(options: QuestionOption[]) {
  const groups = new Map<string, { id: string; documentId: string | null; name: string; options: QuestionOption[] }>();
  for (const option of options) {
    const id = option.document_id ?? `edit:${option.candidate_id}`;
    if (!groups.has(id)) groups.set(id, { id, documentId: option.document_id, name: sourceName(option.document_name), options: [] });
    groups.get(id)!.options.push(option);
  }
  return Array.from(groups.values());
}
// Highlight only literal value matches; source text remains text, including markup/instructions.
export function SourceQuote({ quote, values }: { quote: string; values: unknown[] }) {
  const needles = values.flatMap(value => Array.isArray(value) ? value : [value])
    .filter(value => typeof value === "string" || typeof value === "number")
    .map(String).filter(Boolean).sort((a, b) => b.length - a.length);
  const pattern = needles.length ? new RegExp(`(${Array.from(new Set(needles)).map(value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "giu") : null;
  return <blockquote>“{pattern ? quote.split(pattern).map((part, index) => index % 2 ? <mark key={index}>{part}</mark> : part) : quote}”</blockquote>;
}
export function sourceName(name: string): string {
  const display = name?.trim();
  return !display || /^doc[_-][\w-]+$/i.test(display) ||
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(display)
    ? "Kaynak belge" : display;
}
function optionDisplay(option: QuestionOption): string {
  if (option.summary_tr) return option.summary_tr;
  if (typeof option.value === "boolean") return option.value ? "Evet" : "Hayır";
  if (Array.isArray(option.value)) return option.value.map(value => typeof value === "object" ? JSON.stringify(value) : String(value)).join(", ");
  return option.display || (typeof option.value === "object" ? JSON.stringify(option.value) : String(option.value ?? "—"));
}
export function correctionValue(input: string, example: unknown): unknown {
  const value = input.trim();
  if (typeof example === "number") {
    const number = Number(value.replace(",", "."));
    if (!value || !Number.isFinite(number)) throw new Error("Doğru değeri sayı olarak yazın.");
    return number;
  }
  if (typeof example === "boolean") {
    if (["evet", "var", "doğru"].includes(value.toLocaleLowerCase("tr-TR"))) return true;
    if (["hayır", "yok", "yanlış"].includes(value.toLocaleLowerCase("tr-TR"))) return false;
    throw new Error("Doğru değeri Evet veya Hayır olarak yazın.");
  }
  if (Array.isArray(example) && example.every(item => typeof item === "string")) return value.split(",").map(item => item.trim()).filter(Boolean);
  return value;
}
export function QuestionCard({ question, onAnswer, currentIndex = 1, totalCount, busy = false, readOnly = false, focusOnEnter = false, notice = "", savedAnswer }: {
  question: Question; onAnswer: (answer: QuestionAnswer) => Promise<boolean | void>;
  currentIndex?: number; totalCount: number; busy?: boolean; readOnly?: boolean; focusOnEnter?: boolean; notice?: string;
  savedAnswer?: QuestionAnswer;
}) {
  const inputId = useId();
  const titleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (focusOnEnter) heading.current?.focus({ preventScroll: true }); }, [focusOnEnter]);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<QuestionAnswer | null>(savedAnswer ?? null);
  const [attempt, setAttempt] = useState<QuestionAnswer | null>(null);
  const selection = saved ?? (busy && notice === "Kaydedildi" ? attempt : null);
  const note = notice || (saved && "skip" in saved ? "Bu soruyu sonraya bıraktınız." : saved ? "Kaydedildi" : "");
  const groups = groupByDocument(question.options);
  const schedule = question.kind === "schedule_swap" || question.kind === "schedule_conflict";
  const disabled = submitting || busy || readOnly || saved !== null;
  async function submit(answer: QuestionAnswer) {
    if (disabled) return;
    setSubmitting(true); setError(""); setAttempt(answer);
    try { if (await onAnswer(answer) !== false) { setSaved(answer); setEditing(false); } }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Cevap kaydedilemedi. Tekrar deneyin."); }
    finally { setSubmitting(false); }
  }
  function saveCorrection(event: React.FormEvent) {
    event.preventDefault();
    if (!value.trim()) return;
    try {
      const corrected = correctionValue(value, question.options[0]?.value);
      void submit({ value: corrected, note: "Kullanıcı düzeltmesi" });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Doğru değeri kontrol edin."); }
  }
  return <article className="card questionCard" aria-labelledby={titleId} aria-busy={submitting || busy}>
    <div className="questionIntro">
      <p className="conflictLine"><span className="conflictDot" aria-hidden="true" />{question.kind === "conflict" || schedule ? "Kaynaklar farklı söylüyor" : "İnceleme bekliyor"}<span className="muted">· {question.collection_label}</span></p>
      <h2 id={titleId} ref={heading} tabIndex={-1}>{question.question_tr || `${question.record_title} için ${question.field_label} hangisi?`}</h2>
      {schedule && <p className="sub">{question.records?.join(" ve ")} · {question.period_label_tr}</p>}
      <p className="sub">Güncel belgeyi seçin{question.allow_all ? '; tüm değerler geçerliyse “Hepsi doğru” deyin.' : "; koleksiyonunuz güncellensin."}</p>
    </div>
    <div className="questionOptions">
      {groups.map(group => {
        const chosen = selection && ("all" in selection || ("document_id" in selection && selection.document_id === group.documentId) || ("candidate_id" in selection && group.options.some(option => option.candidate_id === selection.candidate_id)));
        const values = Array.from(new Map(group.options.map(option => [option.candidate_id, option])).values());
        return <section className={`questionOption ${chosen ? "isChosen" : selection && !("skip" in selection) ? "isDim" : ""}`} key={group.id}>
          <p className="documentSays"><Icon name="doc" /><b>{group.name}</b> diyor ki</p>
          <div className="questionValues">{values.map(option => <strong className="questionValue" key={option.candidate_id}>{optionDisplay(option)}</strong>)}</div>
          <div className="questionEvidence">{group.options.map((option, index) => <div key={`${option.candidate_id}:${index}`}>
            {option.evidence ? <details><summary>Kaynakta göster</summary>{option.evidence.map((item, citation) => <div key={citation}><SourceQuote quote={item.quote} values={[option.value]} /><p className="questionSource">{item.locator}</p></div>)}</details> : option.quote ? <SourceQuote quote={option.quote} values={[option.value]} /> : <p className="muted">Sizin düzeltmeniz</p>}
            {option.locator && <p className="questionSource">{option.locator}</p>}
          </div>)}</div>
          <button className="btn" disabled={disabled} onClick={() => void submit(group.documentId ? { document_id: group.documentId } : { candidate_id: group.options[0].candidate_id })} aria-label={`${group.name}: ${group.documentId ? "Bu belge güncel" : "Bu düzeltme doğru"}`}>{chosen ? "Seçildi" : group.documentId ? "Bu belge güncel" : "Bu düzeltme doğru"}</button>
        </section>;
      })}
    </div>
    {error && <p className="inlineError" role="alert">{error}</p>}
    <footer className="questionFooter">
      <div className="questionActions">
        {question.allow_all === true && <button className="btn" disabled={disabled} onClick={() => void submit({ all: true })}>Hepsi doğru</button>}
        {!schedule && <button className="textButton" disabled={disabled} aria-expanded={editing} aria-controls={inputId} onClick={() => setEditing(!editing)}>{groups.length === 2 ? "İkisi de yanlış, düzelt" : groups.length > 2 ? "Hiçbiri doğru değil, düzelt" : "Doğru değil, düzelt"}</button>}
        <button className="textButton muted" disabled={disabled} onClick={() => void submit({ skip: true })}>Sonra sor</button>
        <span className="questionCounter">{currentIndex} / {totalCount}</span>
      </div>
      {editing && <form className="questionCorrection" onSubmit={saveCorrection}>
        <label htmlFor={inputId}>Doğru değer</label>
        <div><input id={inputId} autoFocus value={value} onChange={event => setValue(event.target.value)} placeholder="Doğru bilgiyi yazın" disabled={disabled} required />
          <button className="btn pri" disabled={disabled || !value.trim()} type="submit">Kaydet</button></div>
        {Array.isArray(question.options[0]?.value) && <p className="helper">Birden fazla değeri virgülle ayırın.</p>}
      </form>}
    </footer>
    {note && <div className={`questionNote ${note === "Kaydedildi" ? "" : "neutral"}`} role="status" aria-live="polite"><Icon name={note === "Kaydedildi" ? "check" : "clock"} />{note}</div>}
  </article>;
}
