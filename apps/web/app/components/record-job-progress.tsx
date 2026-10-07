import { useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import type { Mode } from "./console-types";

export type RecordJob = {
  job_id: string; workspace_id: string; status: "queued" | "running" | "needs_review" | "done" | "failed";
  stage: string | null; completed_stages: number; total_stages: number;
  revision_id: string | null; error_code?: string | null;
};
const stages: Record<string, string> = {
  discover: "Listeler bulunuyor", accept_schema: "Bilgi yapısı kontrol ediliyor",
  extract: "Bilgiler çıkarılıyor", match: "Aynı kayıtlar karşılaştırılıyor",
  merge: "Bilgiler birleştiriliyor", publish: "Yayın hazırlanıyor",
};
export const jobActive = (job: RecordJob | null) => job?.status === "queued" || job?.status === "running";

export function useRecordJob(apiUrl: string, workspaceId: string, mode: Mode | null, refreshKey: number, onDone: () => void) {
  const [job, setJob] = useState<RecordJob | null>(null);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [starting, setStarting] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [modelState, setModelState] = useState<"loading" | "ready" | "off" | "error">("loading");
  const scope = useRef<{ controller: AbortController; id: string | null; posting: boolean; requestId: string | null; requestJobId: string | null } | null>(null);
  const finished = useRef("");
  const doneCallback = useRef(onDone); doneCallback.current = onDone;
  const base = `${apiUrl}/v1/workspaces/${encodeURIComponent(workspaceId)}`;
  useEffect(() => {
    const session = { controller: new AbortController(), id: null as string | null, posting: false, requestId: null as string | null, requestJobId: null as string | null };
    try {
      const saved = JSON.parse(localStorage.getItem(`docgrain.record-request:${workspaceId}`) || "null");
      if (typeof saved?.requestId === "string") { session.requestId = saved.requestId; session.requestJobId = saved.jobId ?? null; }
    } catch { /* Optional persistence. */ }
    scope.current = session;
    setJob(null); setError(""); setPollError(""); setStarting(false); setLoaded(false); setModelState("loading"); finished.current = "";
    if (mode !== "live") {
      setLoaded(mode === "demo"); setModelState("off");
      return () => session.controller.abort();
    }
    let reading = false;
    const active = () => !session.controller.signal.aborted && scope.current === session;
    async function poll() {
      if (reading || session.posting || !active()) return;
      reading = true;
      const requestedId = session.id;
      try {
        const response = await fetch(`${base}/record-jobs/${session.id ? encodeURIComponent(session.id) : "latest"}`, { signal: session.controller.signal, cache: "no-store" });
        if (!active() || session.posting || requestedId !== session.id) return;
        if (response.status === 404 && !session.id) { setLoaded(true); setPollError(""); return; }
        if (response.status === 404) {
          setLoaded(false);
          setPollError("Bilgi işinin kaydı bulunamadı. Bağlantıyı kontrol edip listeyi yenileyin.");
          return;
        }
        if (!response.ok) throw new Error();
        const result: RecordJob = await response.json();
        if (!active() || session.posting || requestedId !== session.id) return;
        if (result.workspace_id !== workspaceId || !["queued", "running", "needs_review", "done", "failed"].includes(result.status)) throw new Error();
        session.id = result.job_id; setJob(result); setLoaded(true); setPollError("");
        if (!jobActive(result)) {
          if (session.requestJobId === result.job_id) {
            session.requestId = null; session.requestJobId = null;
            try { localStorage.removeItem(`docgrain.record-request:${workspaceId}`); } catch { /* Optional persistence. */ }
          }
          if (result.status === "done" && finished.current !== result.job_id) {
            finished.current = result.job_id; doneCallback.current();
          }
          session.id = null; // After a terminal job, latest can discover work started in another tab.
        }
      } catch { if (active()) setPollError("Bilgi işinin durumu alınamadı. Bağlantıyı kontrol edin; tekrar kontrol ediliyor."); }
      finally { reading = false; }
    }
    void fetch(`${base}/model`, { signal: session.controller.signal, cache: "no-store" }).then(async response => {
      if (!response.ok) throw new Error();
      const settings = await response.json();
      if (active()) setModelState(settings.enabled && settings.base_url && settings.model && settings.credential_ready ? "ready" : "off");
    }).catch(() => { if (active()) setModelState("error"); });
    void poll();
    const timer = setInterval(() => { void poll(); }, 2000);
    return () => { session.controller.abort(); clearInterval(timer); };
  }, [base, workspaceId, mode, refreshKey]);

  async function start(allowed: boolean) {
    const session = scope.current;
    if (!allowed || mode !== "live" || modelState !== "ready" || !loaded || !session || session.controller.signal.aborted || session.posting || jobActive(job)) return;
    session.posting = true; setStarting(true); setError("");
    const active = () => scope.current === session && !session.controller.signal.aborted;
    try {
      if (!session.requestId) {
        session.requestId ||= crypto.randomUUID();
        try { localStorage.setItem(`docgrain.record-request:${workspaceId}`, JSON.stringify({ requestId: session.requestId, jobId: null })); } catch { /* Retry in this session still uses the same id. */ }
      }
      const response = await fetch(`${base}/record-jobs`, {
        method: "POST", signal: session.controller.signal, headers: { "content-type": "application/json" },
        body: JSON.stringify({ request_id: session.requestId }),
      });
      if (!active()) return;
      if (response.status === 409) {
        setError("Bilgi işi başlatılamadı. Onaylı yayın varsa tekrar çıkarma kapalıdır. Belgelerin hazır olduğunu ve Ayarlar'daki model seçimini kontrol edin; devam eden iş varsa bitmesini bekleyin.");
        return;
      }
      if (response.status === 404) {
        setError("Bilgi çıkarma hizmeti henüz kullanılamıyor. Daha sonra yeniden deneyin.");
        return;
      }
      if (!response.ok) throw new Error();
      const result: { job_id: string } = await response.json();
      if (!active()) return;
      if (!result.job_id) throw new Error();
      session.id = result.job_id; session.requestJobId = result.job_id;
      try { localStorage.setItem(`docgrain.record-request:${workspaceId}`, JSON.stringify({ requestId: session.requestId, jobId: result.job_id })); } catch { /* Optional persistence. */ }
      // The POST supplies an id, not progress. Wait for the server's first detail read.
      setJob(null); setLoaded(false);
    } catch { if (active()) setError("Bilgi işi başlatılamadı. Bağlantıyı kontrol edip yeniden deneyin; aynı istek korunuyor."); }
    finally { if (active()) { session.posting = false; setStarting(false); } }
  }
  return { job, error: error || pollError, starting, loaded, modelState, start };
}

export function RecordJobProgress({ job, error }: { job: RecordJob | null; error: string }) {
  if (!job && !error) return null;
  const title = !job ? "Bilgi işi" : job.status === "done" ? "Bilgiler hazır; onay bekleyenleri Sorular'dan kontrol edin"
    : job.status === "needs_review" ? "Bilgi yapısı kontrol edilmeli"
    : job.status === "failed" ? "Bilgiler çıkarılamadı"
    : job.status === "queued" ? "Bilgi işi sırada" : stages[job.stage ?? ""] || "Bilgiler hazırlanıyor";
  return <Card className="gap-3 border border-line p-4 ring-0 sm:p-5" role={error || job?.status === "failed" ? "alert" : "status"} aria-live="polite">
    <h3 className="text-base font-semibold wrap-anywhere">{title}</h3>
    {job && <p className="text-sm text-muted">{job.completed_stages} / {job.total_stages} aşama tamamlandı{job.status === "failed" && job.stage ? ` · ${stages[job.stage] || "Bilgi hazırlığı"}` : ""}</p>}
    {job?.status === "needs_review" && <p className="text-sm text-warn">Bilgi yapısı güvenle belirlenemedi. Bu iş burada durdu; sorumlu kişiden kontrol isteyin.</p>}
    {job?.status === "failed" && <p className="text-sm text-danger">{job.error_code?.includes("timeout") ? "İşin bekleme süresi doldu." : "Bu aşama tamamlanamadı."} Önceki bilgiler korunuyor. Bağlantıyı ve belgeleri kontrol edin.</p>}
    {error && <p className="text-sm text-danger wrap-anywhere">{error}</p>}
  </Card>;
}
