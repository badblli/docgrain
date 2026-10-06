import { Icon } from "./console-ui";
import type { CollectionSummary } from "./workspace-review";

export function CollectionCard({ collection, onOpen }: { collection: CollectionSummary; onOpen: () => void }) {
  const approved = collection.records > 0 && collection.conflicts === 0 && collection.needs_review === 0;
  return <button className="card collectionCard" onClick={onOpen}>
    <div className="collectionIcon"><Icon name={["rooms", "outlets", "activities"].includes(collection.key) ? collection.key : "grid"} /><Icon name="arrow" /></div>
    <h3>{collection.label}</h3>
    <p>{collection.records.toLocaleString("tr-TR")} kayıt{collection.conflicts > 0 && <span className="conflictText"> · {collection.conflicts} çelişki</span>}</p>
    {approved ? <span className="collectionFoot approvedText"><Icon name="check" />Tamamı onaylı</span> : <span className="collectionFoot muted">{collection.needs_review > 0 ? `${collection.needs_review} kayıt inceleme bekliyor` : "Kayıtları inceleyin"}</span>}
  </button>;
}
