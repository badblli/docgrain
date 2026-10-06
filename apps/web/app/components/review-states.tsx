import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Check, X } from "lucide-react";
import { Icon } from "./console-ui";
import type { LoadState } from "./workspace-review";

export function ReviewBadge({ state }: { state?: string }) {
  const states = {
    proposed: { label: "Öneri", variant: "oneri" }, needs_review: { label: "İnceleme bekliyor", variant: "bekliyor" },
    accepted: { label: "Onaylandı", variant: "onay" }, rejected: { label: "Reddedildi", variant: "red" },
  } as const;
  const review = states[state as keyof typeof states];
  return review ? <Badge variant={review.variant} className="ml-2 align-middle">
    {state === "accepted" ? <Check aria-hidden="true" /> : state === "rejected" ? <X aria-hidden="true" /> : <span className={`size-1.5 rounded-full border border-current ${state === "needs_review" ? "bg-current" : ""}`} aria-hidden="true" />}{review.label}
  </Badge> : null;
}
export function ReviewState({ state, subject, retry }: { state: LoadState; subject: "Özet" | "Sorular"; retry: () => void }) {
  return <Card className="items-center gap-3 border border-dashed border-line-strong px-6 py-10 text-center ring-0" role={state === "error" ? "alert" : "status"} aria-live={state === "loading" ? "polite" : undefined}>
    {state === "loading" ? <Skeleton className="h-1 w-12 bg-accent" /> : <Icon name={subject === "Sorular" ? "question" : "summary"} className="size-9 rounded-full bg-sheet p-2 text-muted" />}
    <h2 className="text-md font-semibold">{state === "loading" ? `${subject} hazırlanıyor…` : state === "missing" ? `${subject} henüz kullanıma hazır değil` : `${subject} alınamadı`}</h2>
    <p className="max-w-[48ch] text-sm text-muted">{state === "loading" ? "Şirketinizin bilgileri alınıyor." : state === "missing" ? "Bu bölüm hazır olduğunda şirketinizin bilgileri burada görünecek." : "Bağlantınızı kontrol edip tekrar deneyin."}</p>
    {state !== "loading" && <Button variant="outline" onClick={retry}>Tekrar dene</Button>}
  </Card>;
}
export function ReviewNotice({ notice }: { notice: string }) {
  return <div className={`flex min-h-6 items-center gap-2 text-sm empty:hidden ${notice === "Kaydedildi" ? "text-ok" : ""}`} role="status" aria-live="polite">{notice && <><Icon name={notice === "Kaydedildi" ? "check" : "clock"} />{notice}</>}</div>;
}
