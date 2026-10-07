"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { ModelState, PublishedListing, TryAnswer, TryProps } from "./types";

type State = "checking" | "ready" | "asking" | "model-off" | "empty" | "no-publication" | "error";
const connectionMessage = "Bağlantı kurulamadı. Lütfen yeniden deneyin.";
const focus = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

// A keyed child clears both the question and answer immediately on company change,
// before effects run. Aborted requests also cannot write into the replacement view.
export function TryView(props: TryProps) {
  return <TrySession key={`${props.apiUrl}:${props.workspaceId}:${props.mode}`} {...props} />;
}

function TrySession({ apiUrl, workspaceId, mode }: TryProps) {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<State>("checking");
  const [answer, setAnswer] = useState<TryAnswer | null>(null);
  const [error, setError] = useState(connectionMessage);
  const [reload, setReload] = useState(0);
  const pending = useRef<AbortController | null>(null);
  const questionId = useId();
  const hintId = useId();
  const base = `${apiUrl.replace(/\/$/, "")}/v1/workspaces/${encodeURIComponent(workspaceId)}`;

  useEffect(() => {
    const controller = new AbortController();
    setState("checking");
    setAnswer(null);
    async function check() {
      if (mode !== "live" || !workspaceId) return;
      try {
        const modelResponse = await fetch(`${base}/model`, { signal: controller.signal, cache: "no-store" });
        if (!modelResponse.ok) throw new Error();
        const model: ModelState = await modelResponse.json();
        if (controller.signal.aborted) return;
        if (!model.enabled || !model.base_url || !model.model || !model.credential_ready) {
          setState("model-off"); return;
        }
        // This existing read-only tool does not call a model or read preview data.
        const response = await fetch(`${base}/ai/call`, {
          method: "POST", signal: controller.signal, cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: "list_collections", arguments: { mode: "approved" } }),
        });
        if (controller.signal.aborted) return;
        if (response.status === 404 || response.status === 409) { setState("no-publication"); return; }
        if (!response.ok) throw new Error();
        const listing: PublishedListing = await response.json();
        if (listing.workspace_id !== workspaceId || listing.mode !== "approved" || !Array.isArray(listing.collections)) throw new Error();
        if (!controller.signal.aborted) setState(listing.collections.some(item => item.record_count > 0) ? "ready" : "empty");
      } catch {
        if (!controller.signal.aborted) { setError(connectionMessage); setState("error"); }
      }
    }
    void check();
    return () => { controller.abort(); pending.current?.abort(); };
  }, [base, mode, workspaceId, reload]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || pending.current || mode !== "live" || !["ready", "error"].includes(state)) return;
    const controller = new AbortController();
    pending.current = controller;
    setState("asking"); setAnswer(null);
    try {
      const response = await fetch(`${base}/ai/ask`, {
        method: "POST", signal: controller.signal, cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim() }),
      });
      if (controller.signal.aborted) return;
      if (!response.ok) {
        if (response.status === 409) {
          // Refresh safe read state after settings/publication changes; no automatic ask retry.
          setReload(value => value + 1); return;
        }
        setError(response.status === 504 ? "Yanıt zamanında alınamadı. Lütfen yeniden deneyin."
          : response.status === 422 ? "Soruyu 1–2000 karakter arasında yazın." : connectionMessage);
        setState("error"); return;
      }
      const result: TryAnswer = await response.json();
      if (result.workspace_id !== workspaceId || result.mode !== "approved" || typeof result.answer !== "string"
        || !Array.isArray(result.sources) || typeof result.abstained !== "boolean") throw new Error();
      if (!controller.signal.aborted) { setAnswer(result); setState("ready"); }
    } catch {
      if (!controller.signal.aborted) { setError(connectionMessage); setState("error"); }
    } finally {
      if (pending.current === controller) pending.current = null;
    }
  }

  const message = mode === "demo" ? "Dene örnek görünümde kapalı. Kendi şirketinizi seçin."
    : mode === null ? "Bağlantı kuruluyor…"
    : !workspaceId ? "Dene için bir şirket seçin."
    : state === "model-off" ? "Dene için Ayarlar'dan model seçip etkinleştirin."
    : state === "no-publication" ? "Henüz yayın yok. Belgeleri hazırlayıp bilgileri onaylayın."
    : state === "empty" ? "Henüz onaylı bilgi yok. Sorular'dan bilgileri onayladıktan sonra burada deneyin."
    : state === "checking" ? "Onaylı bilgiler kontrol ediliyor…" : null;
  const canAsk = mode === "live" && !!workspaceId && (state === "ready" || state === "error");

  function answerText() {
    if (!answer) return null;
    return answer.answer.split(/(\[src_[a-zA-Z0-9_]+\])/g).map((part, index) => {
      const sourceIndex = answer.sources.findIndex(source => `[${source.id}]` === part);
      if (sourceIndex < 0) return part;
      return <a key={index} href={`#${questionId}-source-${sourceIndex}`} className={`mx-1 text-sm text-accent underline underline-offset-4 ${focus}`}
        onClick={() => {
          const source = document.getElementById(`${questionId}-source-${sourceIndex}`);
          if (source instanceof HTMLDetailsElement) source.open = true;
        }}
        aria-label={`${sourceIndex + 1}. kaynak: ${answer.sources[sourceIndex].document_name}`}>[{sourceIndex + 1}]</a>;
    });
  }

  return <section aria-label="Dene" className="mx-auto w-full max-w-4xl px-4 py-8 font-sans text-ink sm:px-8 sm:py-10">
    <header className="mb-8">
      <p className="mb-2 text-xs text-muted">Onaylı bilgilerden cevap</p>
      <h1 className="text-2xl font-semibold tracking-tight">Dene</h1>
      <p className="mt-2 max-w-xl text-base text-ink2">Bir soru sorun. Cevabı, geldiği belge ve alıntıyla birlikte görün.</p>
    </header>
    <form onSubmit={submit} className="rounded-xl border border-line bg-paper p-5 sm:p-6" aria-busy={state === "asking"}>
      <label htmlFor={questionId} className="mb-3 block text-base font-medium">Ne öğrenmek istiyorsunuz?</label>
      <Textarea id={questionId} value={question} onChange={event => setQuestion(event.target.value)}
        placeholder="Örneğin: Bahçe Odası kaç kişilik?" maxLength={2000} required disabled={!canAsk}
        aria-describedby={hintId} className={`min-h-28 resize-y text-base ${focus}`} />
      <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
        <p id={hintId} className="max-w-md text-xs text-muted">Yalnız onayladığınız bilgiler kullanılır. Her soru ayrı değerlendirilir.</p>
        <Button type="submit" disabled={!canAsk || !question.trim()} className={`h-[38px] min-w-24 ${focus}`}>
          {state === "asking" ? "Yanıt hazırlanıyor…" : "Sor"}
        </Button>
      </div>
    </form>
    <div aria-live="polite" aria-atomic="true" className="mt-5">
      {message && <div role="status" className="rounded-xl border border-dashed border-line-strong bg-paper p-5 text-base text-ink2">
        <p>{message}</p>
        {mode === "live" && ["model-off", "empty", "no-publication"].includes(state) &&
          <Button variant="outline" onClick={() => setReload(value => value + 1)} className={`mt-4 h-[38px] ${focus}`}>Yeniden kontrol et</Button>}
      </div>}
      {state === "asking" && <p role="status" className="border-l-2 border-accent py-3 pl-4 text-base text-muted">Onaylı kaynaklar okunuyor…</p>}
      {state === "error" && <div role="alert" className="rounded-xl border border-danger-line bg-danger-soft p-5 text-base text-danger">
        <p>{error}</p><Button variant="outline" className={`mt-4 h-[38px] ${focus}`} onClick={() => setReload(value => value + 1)}>Bağlantıyı yeniden kontrol et</Button>
      </div>}
      {answer && (answer.abstained ? <p className="rounded-xl border border-line bg-paper p-6 text-lg">Bilmiyorum.</p>
        : <article className="rounded-xl border border-line bg-paper p-5 sm:p-6">
          <h2 className="mb-3 text-xs font-medium text-muted">Cevap</h2>
          <p className="whitespace-pre-wrap wrap-anywhere text-lg leading-relaxed">{answerText()}</p>
          <div className="mt-6 border-t border-line2 pt-4">
            <h3 className="mb-2 text-sm font-medium text-ink2">Kaynakta göster</h3>
            {answer.sources.map((source, index) => <details key={source.id} id={`${questionId}-source-${index}`}
              className="mt-2 rounded-lg border border-line2 bg-sheet p-3">
              <summary className={`cursor-pointer wrap-anywhere text-sm text-accent ${focus}`}>{index + 1}. {source.document_name}</summary>
              <blockquote className="my-3 whitespace-pre-wrap wrap-anywhere border-l-2 border-accent-line pl-4 font-serif text-md leading-doc text-ink2">{source.quote}</blockquote>
              <p className="wrap-anywhere font-mono text-xs text-faint">{source.locator}</p>
            </details>)}
          </div>
        </article>)}
    </div>
  </section>;
}
