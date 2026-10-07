import { useCallback, useEffect, useRef, useState } from "react";
import type { Question, QuestionAnswer } from "./question-card";

export type CollectionSummary = {
  key: string; label: string; records: number; conflicts: number; needs_review: number;
  fields?: { key: string; label?: string; label_tr?: string }[];
  accepted_records?: number; pending_records?: number; duplicates?: number;
};
export type SummaryData = {
  workspace_id: string; revision_id: string | null; documents: number; records: number;
  unsupported_fields: number; conflicts: number; needs_review: number; duplicates?: number;
  accepted_ratio: number; updated_at: string | null; collections: CollectionSummary[];
};
export type LoadState = "loading" | "ready" | "missing" | "error";
type QuestionsResponse = { total: number; items: Question[] };
class ResponseError extends Error {
  constructor(readonly status: number) { super("İşlem tamamlanamadı."); }
}
async function read<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal, cache: "no-store" });
  if (!response.ok) throw new ResponseError(response.status);
  return response.json();
}
const failureState = (error: unknown): LoadState =>
  error instanceof ResponseError && [404, 405, 501].includes(error.status) ? "missing" : "error";

// Include every page so filters and field links cover questions beyond the first 20.
async function readQuestions(base: string, revisionId: string, signal: AbortSignal): Promise<QuestionsResponse> {
  const items: Question[] = [];
  let total = 0;
  do {
    const page = await read<QuestionsResponse>(`${base}/questions?limit=20&offset=${items.length}&revision_id=${encodeURIComponent(revisionId)}`, signal);
    if (!Array.isArray(page.items) || !Number.isInteger(page.total) || page.total < 0) throw new Error("Sorular okunamadı.");
    total = page.total;
    if (!page.items.length) break;
    items.push(...page.items);
  } while (items.length < total);
  return { total, items: Array.from(new Map(items.map(item => [item.id, item])).values()) };
}

export function useWorkspaceReview(apiUrl: string, workspaceId: string, refreshKey: number) {
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [summaryState, setSummaryState] = useState<LoadState>("loading");
  const [questions, setQuestions] = useState<Question[]>([]);
  const [questionState, setQuestionState] = useState<LoadState>("loading");
  const [fieldLabels, setFieldLabels] = useState<Record<string, Record<string, string>>>({});
  const learnedLabels = useRef<Record<string, Record<string, string>>>({});
  const [total, setTotal] = useState(0);
  const [deferred, setDeferred] = useState<string[]>([]);
  const [answered, setAnswered] = useState(0);
  const [answeredQuestions, setAnsweredQuestions] = useState<Question[]>([]);
  const [questionAnswers, setQuestionAnswers] = useState<Record<string, QuestionAnswer>>({});
  const questionOrder = useRef<string[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const saving = useRef(false);
  const scope = useRef(0);
  const questionsRevision = useRef<string | null>(null);
  const base = `${apiUrl}/v1/workspaces/${encodeURIComponent(workspaceId)}`;

  const reload = useCallback(async (revisionId?: string) => {
    request.current?.abort();
    setSummaryState(previous => previous === "ready" ? previous : "loading");
    setQuestionState("loading");
    questionsRevision.current = null;
    const controller = new AbortController();
    request.current = controller;
    const active = () => mounted.current && !controller.signal.aborted;
    let summaryData: SummaryData;
    try {
      summaryData = await read<SummaryData>(`${base}/summary${revisionId ? `?revision_id=${encodeURIComponent(revisionId)}` : ""}`, controller.signal);
      if (!Array.isArray(summaryData.collections) || typeof summaryData.records !== "number" ||
        (summaryData.revision_id !== null && typeof summaryData.revision_id !== "string")) {
        throw new Error("Özet okunamadı.");
      }
      if (!active()) return;
      setSummary(summaryData); setSummaryState("ready");
    } catch (error) {
      if (active()) {
        setSummary(null); setSummaryState(failureState(error));
        setQuestions([]); setTotal(0); setQuestionState(failureState(error));
      }
      return;
    }
    if (!summaryData.revision_id) {
      if (active()) { setQuestions([]); setTotal(0); setQuestionState("ready"); }
      return;
    }
    try {
      const data = await readQuestions(base, summaryData.revision_id, controller.signal);
      if (active()) {
        questionsRevision.current = summaryData.revision_id;
        questionOrder.current = [...questionOrder.current, ...data.items.map(item => item.id).filter(id => !questionOrder.current.includes(id))];
        const labels = { ...learnedLabels.current };
        for (const item of data.items) {
          if (item.field_label && item.field_label !== item.field) labels[item.collection] = { ...labels[item.collection], [item.field]: item.field_label };
        }
        learnedLabels.current = labels; setFieldLabels(labels);
        // Keep learned display labels when all questions have been approved and a page is refreshed.
        // Published field metadata, when present, remains the first choice in Collections.
        try { localStorage.setItem(`docgrain.field-labels:${workspaceId}`, JSON.stringify(labels)); } catch { /* Optional display cache. */ }
        setQuestions(data.items); setTotal(data.total); setQuestionState("ready");
      }
    } catch (error) {
      if (active()) { setQuestions([]); setTotal(0); setQuestionState(failureState(error)); }
    }
  }, [base, workspaceId]);

  useEffect(() => {
    mounted.current = true;
    scope.current += 1;
    saving.current = false; setBusy(false);
    setSummaryState("loading"); setQuestionState("loading"); setNotice("");
    setSummary(null); setQuestions([]); setTotal(0); setDeferred([]); setAnswered(0); setAnsweredQuestions([]);
    learnedLabels.current = {};
    try {
      const saved = JSON.parse(localStorage.getItem(`docgrain.field-labels:${workspaceId}`) || "{}");
      if (saved && typeof saved === "object" && !Array.isArray(saved)) {
        for (const [collection, fields] of Object.entries(saved)) {
          if (fields && typeof fields === "object" && !Array.isArray(fields)) learnedLabels.current[collection] = Object.fromEntries(Object.entries(fields).filter(([, label]) => typeof label === "string"));
        }
      }
    } catch { /* Optional display cache. */ }
    setFieldLabels(learnedLabels.current); setQuestionAnswers({}); questionOrder.current = [];
    void reload();
    return () => { mounted.current = false; scope.current += 1; request.current?.abort(); };
  }, [reload, refreshKey]);

  async function answer(question: Question, body: QuestionAnswer) {
    if (saving.current) return false;
    const revisionId = questionsRevision.current;
    if (!revisionId) throw new Error("Sorular güncelleniyor. Biraz sonra tekrar deneyin.");
    saving.current = true;
    setBusy(true); setNotice("");
    const answerScope = scope.current;
    const active = () => mounted.current && scope.current === answerScope;
    try {
      const response = await fetch(`${base}/questions/${encodeURIComponent(question.id)}/answer?revision_id=${encodeURIComponent(revisionId)}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!active()) return false;
      if (response.status === 409) {
        setNotice("Bilgiler değişti; cevabınız kaydedilmedi. Güncel soruları kontrol edin.");
        await reload();
        return false;
      }
      if (!response.ok) throw new Error("Cevap kaydedilemedi. Bağlantıyı kontrol edip tekrar deneyin.");
      const result: { revision_id: string; remaining: number } = await response.json();
      if (!active()) return false;
      if (typeof result.revision_id !== "string" || !result.revision_id || !Number.isInteger(result.remaining) || result.remaining < 0) throw new Error("Cevap doğrulanamadı.");
      if ("skip" in body) {
        setDeferred(previous => [...previous.filter(id => id !== question.id), question.id]);
        setNotice("Bu soruyu sonraya bıraktınız.");
      } else {
        setAnswered(previous => previous + 1);
        setAnsweredQuestions(previous => [...previous.filter(item => item.id !== question.id), question]);
        setQuestionAnswers(previous => ({ ...previous, [question.id]: body }));
        setTotal(result.remaining);
        setDeferred(previous => previous.filter(id => id !== question.id));
        setNotice("Kaydedildi");
      }
      if (active()) await reload(result.revision_id);
      return active();
    } catch {
      if (active()) throw new Error("Cevap kaydedilemedi. Bağlantıyı kontrol edip tekrar deneyin.");
    } finally {
      if (active()) { saving.current = false; setBusy(false); }
    }
  }
  function revisit() { setDeferred([]); setNotice(""); }
  return { fieldLabels, summary, summaryState, questions, questionState, total, answered, answeredQuestions, questionAnswers, questionOrder: questionOrder.current, deferred, notice, busy, reload, answer, revisit };
}
export type WorkspaceReview = ReturnType<typeof useWorkspaceReview>;
