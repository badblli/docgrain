import { Card } from "@/components/ui/card";
import { Icon } from "./console-ui";
import type { CollectionSummary } from "./workspace-review";

export function CollectionCard({ collection, onOpen }: { collection: CollectionSummary; onOpen: () => void }) {
  const accepted = collection.accepted_records ?? 0;
  const pending = collection.pending_records ?? 0;
  const percent = (count: number) => `${collection.records ? count / collection.records * 100 : 0}%`;
  const questions = collection.conflicts + collection.needs_review + (collection.duplicates ?? 0);
  return <Card className="gap-0 border border-line p-0 ring-0 transition-colors hover:border-accent">
    <button className="flex h-full min-w-0 w-full flex-col p-5 text-left" onClick={onOpen}>
      <span className="flex items-start justify-between gap-3 text-accent"><span className="grid size-9 place-items-center rounded-lg border border-line"><Icon name={["rooms", "outlets", "activities"].includes(collection.key) ? collection.key : "grid"} className="size-[18px]" /></span><Icon name="arrow" className="size-[18px] text-faint" /></span>
      <span className="mt-4 text-md font-semibold wrap-anywhere">{collection.label}</span>
      <span className="mb-4 mt-1 text-sm text-muted">Kayıtlar ve belge kaynakları</span>
      <span className="mt-auto flex h-1 overflow-hidden rounded-xs bg-sunken" aria-hidden="true"><i className="h-full bg-ok" style={{ width: percent(accepted) }} /><i className="h-full bg-warn" style={{ width: percent(pending) }} /></span>
      <span className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted"><span>{collection.records.toLocaleString("tr-TR")} kayıt</span><span>{accepted} onaylı</span>{questions > 0 && <span className="text-warn">{questions} soru</span>}</span>
    </button>
  </Card>;
}
