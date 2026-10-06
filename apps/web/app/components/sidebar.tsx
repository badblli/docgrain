import { Icon } from "./console-ui";
import { formatWorkspaceName, type Screen, type WorkspaceItem } from "./console-types";

export function Sidebar({ screen, nav, docs, jobs, questionCount, workspace, workspaces, onWorkspaceChange, developerMode, toggleDeveloperMode, busy }: {
  screen: Screen; nav: (screen: Screen) => void; docs: number; jobs: number;
  questionCount?: number; workspace: string; workspaces: WorkspaceItem[];
  onWorkspaceChange: (id: string) => void; developerMode: boolean;
  toggleDeveloperMode: () => void; busy: boolean;
}) {
  const choices = workspaces.length ? workspaces : [{ id: workspace, documents: docs }];
  return <aside className="rail">
    <button className="brand" onClick={() => nav("summary")} aria-label="Docgrain özetini aç">
      {/* The SVG includes its own OS dark-theme palette. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/brand/logo.svg" alt="Docgrain" width="111" height="22" />
    </button>
    <div className="companySection">
      <label className="navlbl" htmlFor="company-picker">Şirket</label>
      <div className="companySelectWrap">
        <span className="companyAvatar" aria-hidden="true">{formatWorkspaceName(workspace).charAt(0)}</span>
        <div className="companyChoice">
        <select id="company-picker" className="companySelect" value={workspace} disabled={busy} onChange={event => onWorkspaceChange(event.target.value)}>
          {choices.map(item => <option key={item.id} value={item.id}>{formatWorkspaceName(item.id)}</option>)}
        </select>
        <small>{choices.find(item => item.id === workspace)?.documents ?? docs} belge</small>
        </div>
        <span className="companySelectArrow" aria-hidden="true">⇅</span>
      </div>
    </div>
    <nav className="primaryNav" aria-label="Ana menü">
      <button className="nav" aria-current={screen === "summary" ? "page" : undefined} onClick={() => nav("summary")}><Icon name="summary" />Özet</button>
      <button className="nav" aria-current={screen === "questions" ? "page" : undefined} onClick={() => nav("questions")}><Icon name="question" />Sorular{questionCount !== undefined && questionCount > 0 && <span className="questionBadge" aria-label={`${questionCount} açık soru`}>{questionCount}</span>}</button>
      <button className="nav" aria-current={screen === "collections" ? "page" : undefined} onClick={() => nav("collections")}><Icon name="grid" />Koleksiyonlar</button>
      <button className="nav" aria-current={screen === "documents" || screen === "detail" ? "page" : undefined} onClick={() => nav("documents")}><Icon name="doc" />Belgeler</button>
    </nav>
    {developerMode && <nav className="developerNav" aria-label="Geliştirici araçları">
      <div className="navlbl">Geliştirici araçları</div>
      <button className="nav" aria-current={screen === "jobs" ? "page" : undefined} onClick={() => nav("jobs")}><Icon name="clock" />İşler<em>{jobs}</em></button>
      <button className="nav" aria-current={screen === "providers" ? "page" : undefined} onClick={() => nav("providers")}><Icon name="grid" />Sağlayıcılar</button>
      <button className="nav" aria-current={screen === "contract" ? "page" : undefined} onClick={() => nav("contract")}><Icon name="book" />Veri sözleşmesi</button>
    </nav>}
    <div className="railBottom"><label className="switch developerSwitch"><input type="checkbox" role="switch" checked={developerMode} onChange={toggleDeveloperMode} />Geliştirici modu</label><p>Belgeden bilgiye. Kaynağı her zaman yanında.</p></div>
  </aside>;
}
