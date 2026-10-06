import { Icon } from "./console-ui";
import type { CollectionSummary } from "./workspace-review";

export function CollectionCard({ collection, onOpen }: { collection: CollectionSummary; onOpen: () => void }) {
  const accepted = collection.accepted_records ?? 0;
  const pending = collection.pending_records ?? 0;
  const percent = (count: number) => `${collection.records ? count / collection.records * 100 : 0}%`;
  const questions = collection.conflicts + collection.needs_review;
  return <button className="card collectionCard" onClick={onOpen}>
    <div className="collectionIcon"><span><Icon name={["rooms", "outlets", "activities"].includes(collection.key) ? collection.key : "grid"} /></span><Icon name="arrow" /></div>
    <h3>{collection.label}</h3>
    <p>Kayıtlar ve belge kaynakları</p>
    <span className="collectionBar" aria-hidden="true"><i className="ok" style={{ width: percent(accepted) }} /><i className="warn" style={{ width: percent(pending) }} /></span>
    <span className="collectionFoot"><span>{collection.records.toLocaleString("tr-TR")} kayıt</span><span>{accepted} onaylı</span>{questions > 0 && <span className="conflictText">{questions} soru</span>}</span>
  </button>;
}
