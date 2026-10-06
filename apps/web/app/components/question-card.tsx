import { useEffect, useId, useRef, useState } from "react";

export type QuestionOption = {
  candidate_id: string; value: unknown; display: string; quote: string;
  document_name: string; locator: string;
};
export type Question = {
  id: string; kind: string; collection: string; collection_label: string;
  record_id: string; record_title: string; field: string; field_label: string;
  lang: string | null; allow_all?: boolean; options: QuestionOption[];
};
export type QuestionAnswer = { candidate_id: string } | { value: unknown; note: string } | { skip: true } | { all: true };
export function sourceName(name: string): string {
  const display = name?.trim();
  return !display || /^doc[_-][\w-]+$/i.test(display) ||
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(display)
    ? "Kaynak belge" : display;
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
export function QuestionCard({ question, onAnswer, currentIndex = 1, totalCount, busy = false, readOnly = false, focusOnEnter = false }: {
  question: Question; onAnswer: (answer: QuestionAnswer) => Promise<void>;
  currentIndex?: number; totalCount: number; busy?: boolean; readOnly?: boolean; focusOnEnter?: boolean;
}) {
  const inputId = useId();
  const titleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (focusOnEnter) heading.current?.focus({ preventScroll: true }); }, [focusOnEnter]);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const disabled = submitting || busy || readOnly;
  async function submit(answer: QuestionAnswer) {
    if (disabled) return;
    setSubmitting(true); setError("");
    try { await onAnswer(answer); }
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
      <p className="conflictLine"><span className="conflictDot" aria-hidden="true" />Kaynaklar farklı söylüyor · {question.collection_label}</p>
      <h2 id={titleId} ref={heading} tabIndex={-1}>{question.record_title} için {question.field_label} hangisi?</h2>
      <p className="sub">Doğru bilgiyi seçin; koleksiyonunuz güncellensin.</p>
    </div>
    <div className="questionOptions">
      {question.options.map(option => <section className="questionOption" key={option.candidate_id}>
        <strong className="questionValue">{option.display || (typeof option.value === "object" ? JSON.stringify(option.value) : String(option.value ?? "—"))}</strong>
        {option.quote ? <blockquote>“{option.quote}”</blockquote> : <p className="muted">Bu kaynakta alıntı bulunmuyor.</p>}
        <p className="questionSource">{sourceName(option.document_name)}{option.locator ? ` · ${option.locator}` : ""}</p>
        <button className="btn pri" disabled={disabled} onClick={() => void submit({ candidate_id: option.candidate_id })} aria-label={`${option.display || "Bu seçenek"}: Bu doğru`}>Bu doğru</button>
      </section>)}
    </div>
    {question.allow_all === true && <div className="questionAll"><button className="btn" disabled={disabled} onClick={() => void submit({ all: true })}>Hepsi doğru</button></div>}
    {error && <p className="inlineError" role="alert">{error}</p>}
    <footer className="questionFooter">
      <div className="questionActions">
        <button className="textButton" disabled={disabled} aria-expanded={editing} aria-controls={inputId} onClick={() => setEditing(!editing)}>İkisi de yanlış, düzelt</button>
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
  </article>;
}
