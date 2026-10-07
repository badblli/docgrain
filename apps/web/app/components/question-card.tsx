import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { Icon } from "./console-ui";
import { displayCollectionLabel, getFieldLabel } from "./information/labels";

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
  duplicate_records?: {
    id: string; title: string; fields: { key: string; label: string; value: unknown }[];
    sources: { document_id: string | null; document_name: string; locator: string | null; quote: string | null }[];
  }[];
};
export type QuestionAnswer = { candidate_id: string } | { document_id: string } | { value: unknown; note: string } | { skip: true } | { all: true } | { same: boolean };
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
  return <blockquote className="m-0 font-doc text-md leading-doc text-ink2 wrap-anywhere">“{pattern ? quote.split(pattern).map((part, index) => index % 2 ? <mark className="border-b-2 border-accent bg-mark text-inherit" key={index}>{part}</mark> : part) : quote}”</blockquote>;
}
export function sourceName(name: string): string {
  const display = name?.trim();
  return !display || /^doc[_-][\w-]+$/i.test(display) ||
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(display)
    ? "Kaynak belge" : display;
}
function optionDisplay(option: Pick<QuestionOption, "summary_tr" | "value" | "display">): string {
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
  const disabled = submitting || busy || readOnly || saved !== null;
  const schedule = question.kind === "schedule_swap" || question.kind === "schedule_conflict";
  const duplicate = question.kind === "duplicate";
  const confirmation = question.kind === "needs_review" && new Set(question.options.map(option => option.candidate_id)).size === 1;
  const fieldLabel = getFieldLabel(question.field, question.field_label);
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
  return <article aria-labelledby={titleId} aria-busy={submitting || busy} className="min-w-0 self-start motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-right-3 motion-safe:duration-300">
    <Card className="gap-0 border border-line p-0 ring-0">
      <div className="px-4 pt-5 sm:px-6 sm:pt-6">
        <p className="mb-3 flex flex-wrap items-center gap-2 text-xs text-warn"><span className="size-1.5 shrink-0 rounded-full bg-warn" aria-hidden="true" />{duplicate ? "Benzer kayıtlar bulundu" : question.kind === "conflict" || schedule ? "Kaynaklar farklı söylüyor" : confirmation ? "Bu bilgiyi onaylayın" : "İnceleme bekliyor"}<span className="text-muted">· {displayCollectionLabel(question.collection, question.collection_label)}</span></p>
        <h2 className="text-xl leading-snug font-semibold tracking-[-0.02em] wrap-anywhere" id={titleId} ref={heading} tabIndex={-1}>{confirmation ? `${question.record_title} · ${fieldLabel}` : question.question_tr || `${question.record_title} için ${fieldLabel} hangisi?`}</h2>
        {schedule && <p className="mt-1 text-sm text-muted">{question.records?.join(" ve ")} · {question.period_label_tr}</p>}
        <p className="mt-1 text-base text-muted">{duplicate ? "Aynı şeyi anlatıyorlarsa kayıtları birleştirin. Farklı bilgiler için ayrıca soracağız." : confirmation ? "Kaynağı okuyun; bu bilgi doğruysa onaylayın." : <>Güncel belgeyi seçin{question.allow_all ? '; tüm değerler geçerliyse “Hepsi doğru” deyin.' : "; koleksiyonunuz güncellensin."}</>}</p>
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,230px),1fr))] gap-3 p-4 sm:px-6 sm:pb-6 sm:pt-5">
        {duplicate && question.duplicate_records?.map(record => <section className="flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-paper p-4 sm:p-5" key={record.id}>
          <h3 className="text-xl font-medium leading-tight wrap-anywhere">{record.title}</h3>
          <dl className="grid gap-2">{record.fields.map(field => <div key={field.key}>
            <dt className="text-xs text-muted">{field.label === field.key ? getFieldLabel(field.key) : field.label}</dt>
            <dd className="text-sm wrap-anywhere">{optionDisplay({ value: field.value, display: "" })}</dd>
          </div>)}</dl>
          <details className="mt-auto border-t border-line2 pt-3 text-sm"><summary className="cursor-pointer text-accent">Kaynakta göster</summary>
            {record.sources.map((source, index) => <div className="mt-3" key={index}>
              <p className="mb-1 text-xs text-muted wrap-anywhere">{sourceName(source.document_name)}{source.locator && ` · ${source.locator}`}</p>
              {source.quote && <SourceQuote quote={source.quote} values={record.fields.map(field => field.value)} />}
            </div>)}
          </details>
        </section>)}
        {groups.map(group => {
          const chosen = selection && ("all" in selection || ("document_id" in selection && selection.document_id === group.documentId) || ("candidate_id" in selection && group.options.some(option => option.candidate_id === selection.candidate_id)));
          const values = Array.from(new Map(group.options.map(option => [option.candidate_id, option])).values());
          return <section data-document-id={group.id} data-state={chosen ? "chosen" : selection && !("skip" in selection) ? "dimmed" : "open"}
            className={cn("flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-paper p-4 transition-colors sm:p-5", chosen ? "border-accent bg-accent-soft" : selection && !("skip" in selection) ? "opacity-55" : "")} key={group.id}>
            <p className="flex flex-wrap items-center gap-1 text-xs text-muted"><Icon name="doc" className="size-3.5" /><b className="font-medium text-ink2 wrap-anywhere">{group.name}</b> diyor ki</p>
            <div className="grid gap-2">{values.map(option => <strong data-question-value className="text-2xl leading-tight font-medium tracking-[-0.02em] wrap-anywhere" key={option.candidate_id}>{optionDisplay(option)}</strong>)}</div>
            <div className="grid gap-3 border-t border-line2 pt-3">{group.options.map((option, index) => <div key={`${option.candidate_id}:${index}`}>
              {option.evidence ? <details className="text-sm"><summary className="cursor-pointer text-accent">Kaynakta göster</summary>{option.evidence.map((item, citation) => <div className="mt-2" key={citation}><SourceQuote quote={item.quote} values={[option.value]} /><p className="font-mono text-2xs text-faint">{item.locator}</p></div>)}</details> : option.quote ? <SourceQuote quote={option.quote} values={[option.value]} /> : <p className="text-muted">Sizin düzeltmeniz</p>}
              {option.locator && <p className="mt-1 font-mono text-2xs text-faint wrap-anywhere">{option.locator}</p>}
            </div>)}</div>
            <Button variant={chosen ? "default" : "outline"} className={cn("mt-auto h-auto min-h-[38px] max-w-full self-start whitespace-normal", chosen && "disabled:opacity-100")}
              disabled={disabled} onClick={() => void submit(!confirmation && group.documentId ? { document_id: group.documentId } : { candidate_id: group.options[0].candidate_id })} aria-label={`${group.name}: ${confirmation ? "Bu bilgiyi onayla" : group.documentId ? "Bu belge güncel" : "Bu düzeltme doğru"}`}>{chosen ? "Seçildi" : confirmation ? "Bu bilgiyi onayla" : group.documentId ? "Bu belge güncel" : "Bu düzeltme doğru"}</Button>
          </section>;
        })}
      </div>
      {error && <p className="mx-4 mb-5 rounded-lg bg-danger-soft p-3 text-sm text-danger sm:mx-6" role="alert">{error}</p>}
      <footer className="border-t border-line2 px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {duplicate && <>{[true, false].map(same => <Button key={String(same)} variant={selection && "same" in selection && selection.same === same ? "default" : "outline"} disabled={disabled} onClick={() => void submit({ same })}>{same ? "Aynı kayıt" : "Farklı kayıtlar"}</Button>)}</>}
          {question.allow_all === true && <Button variant="outline" disabled={disabled} onClick={() => void submit({ all: true })}>Hepsi doğru</Button>}
          {!schedule && !duplicate && <Button variant="ghost" className="h-auto min-h-[30px] max-w-full whitespace-normal text-left" disabled={disabled} aria-expanded={editing} aria-controls={inputId} onClick={() => setEditing(!editing)}>{groups.length === 2 ? "İkisi de yanlış, düzelt" : groups.length > 2 ? "Hiçbiri doğru değil, düzelt" : "Doğru değil, düzelt"}</Button>}
          <Button variant="ghost" className="text-muted" disabled={disabled} onClick={() => void submit({ skip: true })}>Sonra sor</Button>
          <span className="ml-auto font-mono text-xs text-faint tabular-nums">{currentIndex} / {totalCount}</span>
        </div>
        {editing && <form className="mt-4" onSubmit={saveCorrection}>
          <Label className="mb-2 block text-xs" htmlFor={inputId}>Doğru değer</Label>
          <div className="flex flex-wrap gap-2 sm:flex-nowrap"><Input className="h-[38px] min-w-0 flex-1 basis-full sm:basis-auto" id={inputId} autoFocus value={value} onChange={event => setValue(event.target.value)} placeholder="Doğru bilgiyi yazın" disabled={disabled} required />
            <Button className="h-[38px]" disabled={disabled || !value.trim()} type="submit">Kaydet</Button></div>
          {Array.isArray(question.options[0]?.value) && <p className="mt-2 text-xs text-muted">Birden fazla değeri virgülle ayırın.</p>}
        </form>}
      </footer>
      {note && <div className={cn("flex items-center gap-2 border-t border-ok-line bg-ok-soft px-4 py-3 text-sm text-ok sm:px-6", note !== "Kaydedildi" && "border-line2 bg-sheet text-ink2")} role="status" aria-live="polite"><Icon name={note === "Kaydedildi" ? "check" : "clock"} />{note}</div>}
    </Card>
  </article>;
}
