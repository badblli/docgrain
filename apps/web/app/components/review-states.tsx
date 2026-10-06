import { Icon } from "./console-ui";
import type { LoadState } from "./workspace-review";

export function ReviewState({ state, subject, retry }: { state: LoadState; subject: "Özet" | "Sorular"; retry: () => void }) {
  if (state === "loading") return <div className="card statePanel loadingPanel" role="status" aria-live="polite"><span className="loadingLine" /><h2>{subject} hazırlanıyor…</h2><p>Şirketinizin bilgileri alınıyor.</p></div>;
  return <div className="card statePanel" role={state === "error" ? "alert" : "status"}>
    <Icon name={subject === "Sorular" ? "question" : "summary"} />
    <h2>{state === "missing" ? `${subject} henüz kullanıma hazır değil` : `${subject} alınamadı`}</h2>
    <p>{state === "missing" ? "Bu bölüm hazır olduğunda şirketinizin bilgileri burada görünecek." : "Bağlantınızı kontrol edip tekrar deneyin."}</p>
    <button className="btn" onClick={retry}>Tekrar dene</button>
  </div>;
}
export function ReviewNotice({ notice }: { notice: string }) {
  return <div className={`reviewNotice ${notice === "Kaydedildi" ? "approvedText" : ""}`} role="status" aria-live="polite">{notice && <><Icon name={notice === "Kaydedildi" ? "check" : "clock"} />{notice}</>}</div>;
}
