"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import type { CredentialProfile, WorkspaceModelSettings, WorkspaceModelUpdate, WorkspaceSettingsProps } from "./types";

const emptyForm: WorkspaceModelUpdate = { enabled: false, base_url: "", model: "", credential_id: "" };
const focus = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus)]";

/** The keyed form resets before rendering another company's values, including pending saves. */
export function WorkspaceSettings(props: WorkspaceSettingsProps) {
  return <SettingsForm key={JSON.stringify([props.apiUrl, props.workspaceId, props.mode])} {...props} />;
}

function SettingsForm({ apiUrl, workspaceId, mode, onSaved }: WorkspaceSettingsProps) {
  const id = useId();
  const [form, setForm] = useState<WorkspaceModelUpdate>(emptyForm);
  const [profiles, setProfiles] = useState<CredentialProfile[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error" | "empty">(workspaceId ? "loading" : "empty");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [saveError, setSaveError] = useState(false);
  const [reload, setReload] = useState(0);
  const saveRequest = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const base = `${apiUrl.replace(/\/$/, "")}/v1/workspaces/${encodeURIComponent(workspaceId)}/model`;
  const readOnly = mode === "demo";
  const selectedProfile = profiles.find(profile => profile.id === form.credential_id);
  const canEnable = Boolean(form.base_url.trim() && form.model.trim() && selectedProfile?.ready);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    setForm(emptyForm); setProfiles([]); setMessage(""); setSaveError(false);
    if (!workspaceId) { setState("empty"); return () => { mounted.current = false; controller.abort(); }; }
    setState("loading");
    async function read<T>(url: string): Promise<T> {
      const response = await fetch(url, { signal: controller.signal, cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    }
    void Promise.all([read<WorkspaceModelSettings>(base), read<CredentialProfile[]>(`${base}/profiles`)])
      .then(([settings, options]) => {
        if (controller.signal.aborted) return;
        setForm({ enabled: settings.enabled, base_url: settings.base_url, model: settings.model, credential_id: settings.credential_id });
        setProfiles(options); setState("ready");
      }).catch(error => {
        if (!controller.signal.aborted) setState(error instanceof Error && error.message === "404" ? "empty" : "error");
      });
    return () => { mounted.current = false; controller.abort(); saveRequest.current?.abort(); };
  }, [base, workspaceId, reload]);

  function change(values: Partial<WorkspaceModelUpdate>) {
    setForm(previous => ({ ...previous, ...values })); setMessage(""); setSaveError(false);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readOnly || saving || state !== "ready") return;
    const controller = new AbortController();
    saveRequest.current = controller;
    setSaving(true); setMessage(""); setSaveError(false);
    try {
      const response = await fetch(base, {
        method: "PUT", signal: controller.signal, headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!response.ok) {
        // Fixed messages prevent an upstream error body from being echoed into the UI.
        throw new Error(response.status === 422
          ? "Bağlantıyı, model adını ve hazır bağlantı seçimini kontrol edin."
          : "Ayarlar kaydedilemedi. Bağlantınızı kontrol edip yeniden deneyin.");
      }
      const settings: WorkspaceModelSettings = await response.json();
      if (controller.signal.aborted || !mounted.current) return;
      setForm({ enabled: settings.enabled, base_url: settings.base_url, model: settings.model, credential_id: settings.credential_id });
      setMessage("Kaydedildi."); setSaveError(false);
      onSaved?.(settings);
    } catch (error) {
      if (!controller.signal.aborted && mounted.current) {
        setSaveError(true);
        setMessage(error instanceof Error && error.message.startsWith("Bağlantıyı") ? error.message : "Ayarlar kaydedilemedi. Yeniden deneyin.");
      }
    } finally {
      if (!controller.signal.aborted && mounted.current) setSaving(false);
    }
  }

  return <section className="w-full min-w-0 px-4 pb-16 pt-6 font-sans text-ink md:px-6 md:pt-10 xl:px-10" aria-labelledby={`${id}-title`}>
    {/* The form keeps a comfortable width but stays left-aligned with the header. */}
    <div className="min-w-0 max-w-3xl">
    <header className="mb-6">
      <p className="mb-1 text-xs text-muted">Çalışma alanı</p>
      <h1 id={`${id}-title`} className="text-2xl font-semibold tracking-tight">Ayarlar</h1>
      <p className="mt-2 max-w-[74ch] text-base text-ink2">Bu çalışma alanının bilgi çıkarma ve soru yanıtlama bağlantısı.</p>
    </header>
    {state === "loading" && <Card className="gap-4 border border-line p-5 ring-0" role="status" aria-live="polite">
      <p>Ayarlar yükleniyor.</p><Skeleton className="h-9 w-full" /><Skeleton className="h-9 w-2/3" />
    </Card>}
    {state === "empty" && <Card className="border border-dashed border-line-strong p-5 ring-0">
      <h2 className="text-md font-semibold">Çalışma alanı seçin</h2>
      <p className="text-ink2">Ayarları görmek için bir çalışma alanı seçin veya yeni bir tane oluşturun.</p>
    </Card>}
    {state === "error" && <Card className="border border-line p-5 ring-0">
      <p role="alert" className="text-danger">Ayarlar yüklenemedi. Bağlantınızı kontrol edip yeniden deneyin.</p>
      <Button variant="outline" className={`h-[38px] self-start ${focus}`} onClick={() => setReload(value => value + 1)}>Yeniden dene</Button>
    </Card>}
    {state === "ready" && <Card className="gap-0 border border-line p-0 ring-0">
      <div className="border-b border-line2 px-5 py-4 sm:px-6">
        <h2 className="text-md font-semibold">Model bağlantısı</h2>
        <p id={`${id}-notice`} className="mt-2 text-base leading-relaxed text-ink2">
          Modeli açtığınızda, “Bilgileri çıkar” veya “Sor” işlemiyle düzenlenmiş belge içeriği seçtiğiniz bağlantıya gönderilir.
          Kaydetmek veya belge yüklemek modeli çalıştırmaz.
        </p>
      </div>
      <form onSubmit={save} className="min-w-0 p-5 sm:p-6" aria-describedby={`${id}-notice`}>
        {readOnly && <p className="mb-5 rounded-lg border border-line bg-sheet p-3 text-muted">Örnek görünümde ayarlar değiştirilemez.</p>}
        <fieldset disabled={readOnly || saving} className="min-w-0 space-y-5">
          <legend className="sr-only">Model bağlantısını düzenle</legend>
          <div className="space-y-2">
            <Label htmlFor={`${id}-url`}>Bağlantı adresi</Label>
            <Input id={`${id}-url`} type="url" autoComplete="off" spellCheck={false} maxLength={2048}
              placeholder="https://model.example/v1" className={`h-[38px] ${focus}`}
              value={form.base_url} onChange={event => change({ base_url: event.target.value })} />
            <p className="text-xs text-muted">Size verilen bağlantı adresini yazın. Adrese anahtar eklemeyin.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${id}-model`}>Model adı</Label>
            <Input id={`${id}-model`} autoComplete="off" spellCheck={false} maxLength={256}
              className={`h-[38px] ${focus}`} value={form.model} onChange={event => change({ model: event.target.value })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${id}-profile`}>Hazır bağlantı seçimi</Label>
            <select id={`${id}-profile`} className={`h-[38px] w-full min-w-0 rounded-lg border border-line bg-paper px-2.5 text-base text-ink disabled:opacity-50 ${focus}`}
              value={form.credential_id} onChange={event => change({ credential_id: event.target.value })} aria-describedby={`${id}-credential`}>
              <option value="">Bir seçenek seçin</option>
              {form.credential_id && !selectedProfile && <option value={form.credential_id}>Seçilen bağlantı artık kullanılamıyor</option>}
              {profiles.map(profile => <option key={profile.id} value={profile.id} disabled={!profile.ready}>
                {profile.label}{profile.ready ? " · Hazır" : " · Hazır değil"}
              </option>)}
            </select>
            <p id={`${id}-credential`} className={`text-xs ${!selectedProfile?.ready ? "text-warn" : "text-muted"}`}>
              {!profiles.length ? "Henüz hazır bağlantı yok. Yöneticinizden bir bağlantı hazırlamasını isteyin."
                : form.credential_id && !selectedProfile?.ready ? "Seçilen bağlantı hazır değil. Yöneticinizden kontrol etmesini isteyin."
                  : "Bağlantı anahtarları sunucuda tutulur; bu ekrana gönderilmez."}
            </p>
          </div>
          <div className="rounded-lg border border-line bg-sheet p-4">
            <label htmlFor={`${id}-enabled`} className="flex cursor-pointer items-start gap-3">
              <input id={`${id}-enabled`} type="checkbox" className={`mt-1 size-4 shrink-0 accent-[var(--accent)] ${focus}`}
                checked={form.enabled} disabled={!form.enabled && !canEnable}
                onChange={event => change({ enabled: event.target.checked })} aria-describedby={`${id}-enabled-help`} />
              <span><span className="block text-base font-medium">Modeli aç</span>
                <span id={`${id}-enabled-help`} className="mt-1 block text-sm text-muted">
                  {form.enabled ? "Açık seçildi. Kaydettiğinizde sonraki işlemlerde kullanılabilir."
                    : "Kapalı. Açmak için bağlantı, model adı ve hazır bir seçenek seçin."}
                </span>
              </span>
            </label>
          </div>
        </fieldset>
        <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-line2 pt-4">
          <Button type="submit" disabled={readOnly || saving || (form.enabled && !canEnable)} className={`h-[38px] px-5 ${focus}`}>
            {saving ? "Kaydediliyor…" : "Kaydet"}
          </Button>
          <p role={saveError ? "alert" : "status"} aria-live="polite" className={`min-w-0 text-sm ${saveError ? "text-danger" : "text-ok"}`}>{message}</p>
        </div>
      </form>
    </Card>}
    </div>
  </section>;
}
