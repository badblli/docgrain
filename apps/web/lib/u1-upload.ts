import type { UploadState } from "../app/components/console-types";
import { NOT_ENABLED_MESSAGE } from "./source-formats";

export type UploadRegistration = {
  document: { id: string; filename?: string };
  version: { id: string; status: string };
  job_id: string; upload_url: string | null; deduplicated: boolean;
};
// A refusal the person can act on; shown as is instead of the generic retry message.
class UploadMessage extends Error {}

export async function sha256(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

// This queue ends at upload confirmation. Document preparation is followed separately.
// One queue belongs to one workspace generation; callbacks and further writes stop when stale.
export function createUploadQueue<R extends UploadRegistration>(options: {
  apiUrl: string; workspaceId: string; fetch: typeof fetch;
  hash: (file: File) => Promise<string>; active: () => boolean; signal?: AbortSignal;
  onState: (state: UploadState) => void; onRegistered: (registration: R) => void;
  onUploaded: (registration: R, id: string) => void; concurrency?: number;
}) {
  type Item = { id: string; file: File; registration?: R; stored?: boolean; failed?: boolean };
  const items = new Map<string, Item>();
  const content = new Map<string, Promise<R>>();
  const pending: Item[] = [];
  let running = 0, sequence = 0;
  const current = () => options.active() && !options.signal?.aborted;
  const state = (item: Item, phase: UploadState["phase"], message: string) => {
    if (current()) options.onState({ id: item.id, fileName: item.file.name, jobId: item.registration?.job_id, phase, message });
  };
  async function json<T>(url: string, init: RequestInit): Promise<T> {
    if (!current()) throw new Error("Eski şirket isteği.");
    const response = await options.fetch(url, { ...init, signal: options.signal });
    if (!response.ok) {
      // WP106: Docling can read the type, but this installation has not opened it yet.
      if (response.status === 415 && (await response.json().catch(() => null))?.detail === NOT_ENABLED_MESSAGE) throw new UploadMessage(NOT_ENABLED_MESSAGE);
      throw new Error("Dosya yüklenemedi. Bağlantıyı ve dosyayı kontrol edip yeniden deneyin.");
    }
    if (!current()) throw new Error("Eski şirket isteği.");
    return response.json();
  }
  async function protocol(item: Item, hash: string): Promise<R> {
    if (!item.registration) {
      state(item, "registering", "Belge kaydediliyor…");
      item.registration = await json<R>(`${options.apiUrl}/v1/documents`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ workspace_id: options.workspaceId, filename: item.file.name,
          mime_type: item.file.type || "application/octet-stream", byte_size: item.file.size, content_sha256: hash }),
      });
    }
    const registration = item.registration;
    if (current()) options.onRegistered(registration);
    if (registration.upload_url && !item.stored) {
      state(item, "uploading", "Dosya yükleniyor…");
      const form = new FormData();
      form.append("file", item.file, registration.document.filename || item.file.name);
      await json(registration.upload_url, { method: "PUT", body: form });
      item.stored = true;
    } else if (!registration.deduplicated && !registration.upload_url) {
      throw new Error("Dosya yüklenemedi. Yeniden deneyin.");
    }
    if (!registration.deduplicated || registration.upload_url) {
      state(item, "confirming", "Dosya kontrol ediliyor…");
      await json(`${options.apiUrl}/v1/documents/${encodeURIComponent(registration.document.id)}/versions/${encodeURIComponent(registration.version.id)}/uploaded`, { method: "POST" });
    }
    return registration;
  }
  async function run(item: Item) {
    try {
      state(item, "hashing", "Dosya kontrol ediliyor…");
      const hash = await options.hash(item.file);
      if (!current()) return;
      let result = content.get(hash);
      if (!result) {
        result = protocol(item, hash);
        content.set(hash, result);
        // A failed transfer can be retried without reserving duplicate content forever.
        void result.catch(() => { if (content.get(hash) === result) content.delete(hash); });
      }
      const registration = await result;
      if (!current()) return;
      item.registration = registration; item.failed = false;
      state(item, registration.version.status === "done" ? "done" : "queued",
        registration.deduplicated ? "Aynı dosya zaten var. Mevcut belge kullanılıyor." : "Yüklendi; belge hazırlanmayı bekliyor.");
      options.onUploaded(registration, item.id);
    } catch (error) {
      item.failed = true;
      state(item, "error", error instanceof UploadMessage ? error.message : "Dosya yüklenemedi. Bağlantıyı ve dosyayı kontrol edip yeniden deneyin.");
    }
  }
  const limit = Math.max(1, Math.min(3, options.concurrency ?? 2));
  function pump() {
    while (current() && running < limit && pending.length) {
      const item = pending.shift()!;
      running += 1;
      void run(item).finally(() => { running -= 1; pump(); });
    }
  }
  return {
    add(files: File[]) {
      if (!current()) return;
      for (const file of files) {
        const item = { id: `upload-${++sequence}`, file };
        items.set(item.id, item); pending.push(item);
        state(item, "waiting", "Yükleme sırasında…");
      }
      pump();
    },
    retry(id: string) {
      const item = items.get(id);
      if (!current() || !item?.failed) return;
      item.failed = false; pending.push(item);
      state(item, "waiting", "Yükleme sırasında…"); pump();
    },
  };
}
