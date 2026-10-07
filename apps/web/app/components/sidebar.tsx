import { useId, useState } from "react";
import { Input } from "@/components/ui/input";
import { Menu } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Icon } from "./console-ui";
import { formatWorkspaceName, type Screen, type WorkspaceItem } from "./console-types";

function BrandLogo() {
  return <span className="inline-flex items-center">
    {/* Static variants also follow a forced .dark or data-theme setting. */}
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src="/brand/logo-light.svg" alt="Docgrain" width="111" height="22" className="h-[22px] w-auto dark:hidden" />
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src="/brand/logo-dark.svg" alt="Docgrain" width="111" height="22" className="hidden h-[22px] w-auto dark:block" />
  </span>;
}

type SidebarProps = {
  screen: Screen; nav: (screen: Screen) => void; docs: number; jobs: number;
  questionCount?: number; workspace: string; workspaces: WorkspaceItem[];
  onWorkspaceChange: (id: string) => void; developerMode: boolean;
  toggleDeveloperMode: () => void; busy: boolean; readOnly?: boolean; onCreateWorkspace?: (name: string) => Promise<boolean>;
};
function SidebarContent({ screen, nav, docs, jobs, questionCount, workspace, workspaces, onWorkspaceChange, developerMode, toggleDeveloperMode, readOnly, onCreateWorkspace }: SidebarProps) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const pickerId = useId();
  const switchId = useId();
  const choices = workspaces.length ? workspaces : [{ id: workspace, documents: docs }];
  const companyName = formatWorkspaceName(workspace, choices.find(item => item.id === workspace)?.name);
  const navigation = (target: Screen, name: string, icon: string, count?: number) => <Button key={target} variant="ghost"
    className="h-[38px] w-full justify-start gap-3 rounded-lg px-3 text-sm text-ink2 transition-none aria-[current=page]:bg-accent-soft aria-[current=page]:font-semibold aria-[current=page]:text-accent"
    aria-current={screen === target || (target === "documents" && screen === "detail") ? "page" : undefined} onClick={() => nav(target)}>
    <Icon name={icon} className="size-[18px]" />{name}
    {count !== undefined && count > 0 && <Badge variant={target === "questions" ? "bekliyor" : "secondary"} className="ml-auto rounded-sm" aria-label={target === "questions" ? `${count} açık soru` : undefined}>{count}</Badge>}
  </Button>;
  return <div className="flex h-full min-h-0 flex-col gap-6 overflow-y-auto px-4 py-6">
    <Button variant="ghost" className="h-[30px] justify-start px-2" onClick={() => nav("summary")} aria-label="Docgrain özetini aç">
      <BrandLogo />
    </Button>
    <div className="grid gap-2">
      <Label htmlFor={pickerId} className="px-2 text-xs text-muted">Şirket</Label>
      <div className="flex min-w-0 items-center gap-2 rounded-lg border border-line bg-paper p-2">
        <Avatar className="size-[26px] rounded-sm"><AvatarFallback className="rounded-sm bg-accent-soft text-xs font-semibold text-accent">{companyName.charAt(0)}</AvatarFallback></Avatar>
        <div className="min-w-0 flex-1">
          <Select value={workspace} onValueChange={id => { if (id === "__new__") { setCreating(true); setError(""); } else { setCreating(false); setError(""); onWorkspaceChange(id); } }}>
            <SelectTrigger id={pickerId} className="h-auto w-full min-w-0 border-0 bg-paper p-0 text-sm font-semibold shadow-none"><SelectValue>{companyName}</SelectValue></SelectTrigger>
            <SelectContent>{choices.map(item => <SelectItem key={item.id} value={item.id}>{formatWorkspaceName(item.id, item.name)}</SelectItem>)}{onCreateWorkspace && !readOnly && <SelectItem value="__new__">Yeni şirket</SelectItem>}</SelectContent>
          </Select>
          <small className="block text-2xs text-muted">{choices.find(item => item.id === workspace)?.documents ?? docs} belge</small>
        </div>
      </div>
      {creating && <form className="grid min-w-0 gap-2 rounded-lg border border-line p-3" onSubmit={async event => {
        event.preventDefault(); if (saving || !name.trim() || !onCreateWorkspace) return;
        setSaving(true); setError("");
        try { if (await onCreateWorkspace(name.trim())) { setCreating(false); setName(""); } else setError("Şirket oluşturulamadı. Bağlantıyı kontrol edip yeniden deneyin."); }
        catch { setError("Şirket oluşturulamadı. Bağlantıyı kontrol edip yeniden deneyin."); }
        finally { setSaving(false); }
      }}>
        <Label htmlFor={`${pickerId}-new`}>Şirket adı</Label><Input id={`${pickerId}-new`} autoFocus value={name} maxLength={200} onChange={event => setName(event.target.value)} required disabled={saving} />
        {error && <p className="text-xs text-danger" role="alert">{error}</p>}
        <Button type="submit" disabled={saving || !name.trim()}>{saving ? "Oluşturuluyor…" : "Şirket oluştur"}</Button><Button variant="ghost" type="button" disabled={saving} onClick={() => setCreating(false)}>Vazgeç</Button>
      </form>}
    </div>
    <nav className="grid gap-1" aria-label="Ana menü">
      {navigation("summary", "Özet", "summary")}{navigation("questions", "Sorular", "question", questionCount)}
      {navigation("collections", "Koleksiyonlar", "grid")}{navigation("documents", "Belgeler", "doc")}
      {navigation("try", "Dene", "question")}{navigation("settings", "Ayarlar", "book")}
    </nav>
    {developerMode && <nav className="grid gap-1" aria-label="Geliştirici araçları">
      <p className="text-xs text-muted p-2">Geliştirici araçları</p>
      {navigation("jobs", "İşler", "clock", jobs)}{navigation("providers", "Sağlayıcılar", "grid")}{navigation("contract", "Veri sözleşmesi", "book")}
    </nav>}
    <div className="mt-auto pt-8">
      <Label htmlFor={switchId} className="mx-2 flex items-center gap-2 text-xs font-normal text-muted"><input id={switchId} className="size-4 accent-accent" type="checkbox" role="switch" checked={developerMode} onChange={toggleDeveloperMode} />Geliştirici modu</Label>
      <p className="mx-2 mt-4 text-2xs text-faint">Belgeden bilgiye. Kaynağı her zaman yanında.</p>
    </div>
  </div>;
}
export function Sidebar(props: SidebarProps) {
  const [open, setOpen] = useState(false);
  const mobileProps = { ...props, nav: (screen: Screen) => { props.nav(screen); setOpen(false); } };
  return <>
    <aside className="sticky top-0 hidden h-dvh min-w-0 border-r border-line bg-paper md:block"><SidebarContent {...props} /></aside>
    <div className="flex items-center justify-between border-b border-line bg-paper px-4 py-3 md:hidden">
      <Button variant="ghost" className="h-auto p-0" onClick={() => props.nav("summary")} aria-label="Docgrain özetini aç"><BrandLogo /></Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild><Button variant="outline" size="icon" aria-label="Menüyü aç"><Menu className="size-5" /></Button></SheetTrigger>
        <SheetContent side="left" className="gap-0 p-0 data-[side=left]:w-[min(320px,90vw)]">
          <SheetHeader className="sr-only"><SheetTitle>Ana menü</SheetTitle><SheetDescription>Şirket seçimi ve çalışma alanı bölümleri.</SheetDescription></SheetHeader>
          <SidebarContent {...mobileProps} />
        </SheetContent>
      </Sheet>
    </div>
  </>;
}
