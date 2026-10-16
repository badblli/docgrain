"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export type FieldDefinition = { key: string; label: string; type: string };
export type CollectionDefinition = { key: string; label: string; identity: string; fields: FieldDefinition[] };
export type CollectionSchema = { version: number; collections: CollectionDefinition[]; field_notes?: Record<string, string> };
type Action = "field" | "collection" | "record" | "value";
const types = [
  ["string", "Metin"], ["integer", "Tam sayı"], ["number", "Sayı"],
  ["boolean", "Evet / hayır"], ["string_list", "Liste"],
];
const keyFrom = (label: string) => label.toLocaleLowerCase("tr-TR")
  .replace(/[çğıöşü]/g, char => ({ ç: "c", ğ: "g", ı: "i", ö: "o", ş: "s", ü: "u" } as Record<string, string>)[char] ?? char)
  .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
function parseValue(input: string, type: string): unknown {
  if (type === "boolean") return input === "true";
  if (type === "integer" || type === "number") {
    const number = Number(input);
    if (!input.trim() || !Number.isFinite(number) || (type === "integer" && !Number.isInteger(number))) throw Error("Geçerli bir sayı girin.");
    return number;
  }
  if (type === "string_list") return input.split(/[,\n]/).map(item => item.trim()).filter(Boolean);
  if (!input.trim()) throw Error("Bir değer girin.");
  return input.trim();
}

export function CollectionActions({ base, revision, schema, collection, record, field, developerMode, onDone }: {
  base: string; revision: string; schema: CollectionSchema | null; collection?: string;
  record?: string; field?: string; developerMode: boolean; onDone: (message: string) => void;
}) {
  const [action, setAction] = useState<Action | null>(null);
  const [label, setLabel] = useState("");
  const [key, setKey] = useState("");
  const [type, setType] = useState("string");
  const [description, setDescription] = useState("");
  const [fields, setFields] = useState<{ label: string; key: string; type: string; value: string }[]>([{ label: "Ad", key: "name", type: "string", value: "" }]);
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const definition = schema?.collections.find(item => item.key === collection);
  const selectedField = definition?.fields.find(item => item.key === field);
  const open = (next: Action) => { setAction(next); setError(""); setValue(""); setNote(""); setLabel(""); setKey(""); setType("string"); setDescription("");
    setFields(next === "record" ? (definition?.fields.map(item => ({ ...item, value: "" })) ?? []) : [{ label: "Ad", key: "name", type: "string", value: "" }]); };
  const updateField = (index: number, patch: Partial<(typeof fields)[number]>) => setFields(previous => previous.map((item, at) => at === index ? { ...item, ...patch } : item));
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!action || !schema) return;
    setBusy(true); setError("");
    try {
      const collectionKey = key || keyFrom(label);
      const fieldKey = key || keyFrom(label);
      const endpoint = action === "collection" ? "/collections" : action === "field" ? `/collections/${encodeURIComponent(collection!)}/fields` :
        action === "record" ? `/collections/${encodeURIComponent(collection!)}/records` : `/records/${encodeURIComponent(record!)}/fields/${encodeURIComponent(field!)}`;
      const body = action === "collection" ? { key: collectionKey.endsWith("s") ? collectionKey : `${collectionKey}s`, label, identity: fields[0].key || keyFrom(fields[0].label), fields: fields.map(item => ({ key: item.key || keyFrom(item.label), label: item.label, type: item.type })) } :
        action === "field" ? { key: fieldKey, label, type, description: description || null } :
          action === "record" ? { values: Object.fromEntries(fields.filter(item => item.value.trim()).map(item => [item.key, parseValue(item.value, item.type)])), note } :
            { value: parseValue(value, selectedField?.type ?? "string"), note };
      const response = await fetch(`${base}${endpoint}?revision_id=${encodeURIComponent(revision)}`, {
        method: action === "value" ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!response.ok) {
        setError(response.status === 409 ? "Bu sırada bilgiler değişti veya hazırlanıyor. Yenileyip tekrar deneyin." : response.status === 422 ? "Girdiğiniz bilgileri kontrol edin." : "İşlem tamamlanamadı. Tekrar deneyin.");
        return;
      }
      const result = await response.json();
      setAction(null);
      onDone(result.note || "Değişiklik düzenleme geçmişine eklendi.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "İşlem tamamlanamadı."); }
    finally { setBusy(false); }
  }
  if (!schema || !revision) return null;
  return <>
    {!collection && <Button onClick={() => open("collection")}>Koleksiyon ekle</Button>}
    {collection && !record && <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => open("field")}>Alan ekle</Button><Button onClick={() => open("record")}>Kayıt ekle</Button></div>}
    {record && field && <Button variant="ghost" size="sm" onClick={() => open("value")}>Düzenle</Button>}
    <Dialog open={!!action} onOpenChange={isOpen => { if (!isOpen && !busy) setAction(null); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader><DialogTitle>{action === "field" ? "Alan ekle" : action === "collection" ? "Koleksiyon ekle" : action === "record" ? "Kayıt ekle" : "Değeri düzenle"}</DialogTitle>
          <DialogDescription>{action === "field" ? "Model açıksa belgelerinizdeki değerler aranır." : "Eklediğiniz bilgi düzenleme geçmişine kaydedilir."}</DialogDescription></DialogHeader>
        <form className="grid gap-4" onSubmit={submit}>
          {(action === "field" || action === "collection") && <><Label>Ad<Input required value={label} onChange={event => setLabel(event.target.value)} /></Label>
            {developerMode && <Label>Kod<Input value={key} onChange={event => setKey(event.target.value)} placeholder={keyFrom(label)} /></Label>}</>}
          {action === "field" && <><Label>Bilgi türü<select className="mt-1 w-full rounded-lg border border-line bg-sheet p-2" value={type} onChange={event => setType(event.target.value)}>{types.map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select></Label>
            <Label>Açıklama (isteğe bağlı)<Textarea value={description} onChange={event => setDescription(event.target.value)} /></Label></>}
          {(action === "collection" || action === "record") && <div className="grid gap-3"><p className="text-sm font-semibold">Alanlar</p>{fields.map((item, index) => <div className="grid gap-2 rounded-lg border border-line p-3" key={index}>
            {action === "collection" ? <><Label>Alan adı<Input required value={item.label} onChange={event => updateField(index, { label: event.target.value, key: keyFrom(event.target.value) })} /></Label>
              {developerMode && <Label>Kod<Input value={item.key} onChange={event => updateField(index, { key: event.target.value })} /></Label>}
              <Label>Bilgi türü<select className="mt-1 w-full rounded-lg border border-line bg-sheet p-2" value={item.type} onChange={event => updateField(index, { type: event.target.value })}>{types.map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select></Label></> :
              <Label>{item.label}{item.key === definition?.identity ? " *" : ""}{item.type === "boolean" ? <select className="mt-1 w-full rounded-lg border border-line bg-sheet p-2" value={item.value} onChange={event => updateField(index, { value: event.target.value })}><option value="">Seçin</option><option value="true">Evet</option><option value="false">Hayır</option></select> : <Input required={item.key === definition?.identity} value={item.value} onChange={event => updateField(index, { value: event.target.value })} placeholder={item.type === "string_list" ? "Değerleri virgülle ayırın" : ""} />}</Label>}
          </div>)}{action === "collection" && <Button type="button" variant="outline" onClick={() => setFields(previous => [...previous, { label: "", key: "", type: "string", value: "" }])}>Alan ekle</Button>}</div>}
          {action === "value" && <Label>Yeni değer{selectedField?.type === "boolean" ? <select className="mt-1 w-full rounded-lg border border-line bg-sheet p-2" value={value} onChange={event => setValue(event.target.value)}><option value="">Seçin</option><option value="true">Evet</option><option value="false">Hayır</option></select> : <Textarea required value={value} onChange={event => setValue(event.target.value)} />}</Label>}
          {(action === "record" || action === "value") && <Label>Not (isteğe bağlı)<Textarea value={note} onChange={event => setNote(event.target.value)} /></Label>}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <DialogFooter><Button type="submit" disabled={busy}>{busy ? "Kaydediliyor…" : "Kaydet"}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  </>;
}
