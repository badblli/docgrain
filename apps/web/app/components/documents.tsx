import { useRef } from "react";
import { useDeveloperMode } from "./developer-mode";
import { Head, Icon, Ep } from "./console-ui";
import type { DocumentRow, UploadState, Mode } from "./console-types";

function Status({ status }: { status: string }) {
  const label = status === "done" ? "Hazır" : ["queued", "pending"].includes(status) ? "Sırada" : ["running", "processing"].includes(status) ? "Hazırlanıyor" : "Kontrol edilmeli";
  return <span className="documentStatus">{label}</span>;
}

export function Documents({
  docs,
  open,
  upload,
  uploadState,
  mode,
}: {
  docs: DocumentRow[];
  open: (d: DocumentRow) => void;
  upload: (file: File) => Promise<void>;
  uploadState: UploadState;
  mode: Mode | null;
}) {
  const developerMode = useDeveloperMode();
  const input = useRef<HTMLInputElement>(null);
  const busy = mode !== "live" || ["registering", "uploading", "confirming", "queued", "running"].includes(
    uploadState.phase,
  );
  return (
    <>
      <Head
        title="Belgeler"
        sub="Belgelerinizi yükleyin, durumlarını takip edin ve içeriklerini okuyun."
        endpoint="GET /v1/documents"
      />
      <div className="wrap">
        <section className="drop documentUpload">
          <div className="ico">
            <Icon name="upload" />
          </div>
          <div>
            <h3>Yeni bir belge ekleyin</h3>
            <p>
              PDF, Word, Excel, metin veya görsel dosyalarınızı ekleyin.
            </p>
            {uploadState.phase !== "idle" && (
              <div className={`uploadState upload-${uploadState.phase}`} role="status">
                <span className="uploadDot" />
                <b>{uploadState.fileName}</b>
                <span>{developerMode || uploadState.phase !== "error" ? uploadState.message : "Dosya yüklenemedi. Bağlantıyı kontrol edip yeniden deneyin."}</span>
                {developerMode && uploadState.jobId && <code>{uploadState.jobId}</code>}
              </div>
            )}
          </div>
          <input
            ref={input}
            type="file"
            hidden
            // Use one extension list so native pickers do not select a PDF-only MIME filter.
            accept=".pdf,.docx,.xlsx,.txt,.png,.jpg,.jpeg"
            aria-label="Dosya yükle: PDF, DOCX, XLSX, TXT, PNG, JPG veya JPEG"
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              void upload(file).finally(() => {
                if (input.current) input.current.value = "";
              });
            }}
          />
          <button
            className="btn dropAction"
            onClick={() => input.current?.click()}
            disabled={busy}
          >
            {mode === "demo" ? "Örnek görünüm: yükleme kapalı" : mode === null ? "Bağlanıyor…" : busy ? "İşleniyor…" : "Dosya yükle"}
          </button>
        </section>
        <section className="card documentList">
          <header>
            <h2>Tüm belgeler</h2>
            <p className="note">
              İçeriğini okumak için bir belge açın.
            </p>
            <span className="sp">
              <Ep>GET /v1/documents?limit=50</Ep>
            </span>
          </header>
          <div className="scrollx">
            <table className="grid docs">
              <thead>
                <tr>
                  <th>Belge</th>
                  <th>Durum</th>
                  <th>Sürüm</th>
                  <th>Sayfa</th>
                  <th>Son işlem</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {!docs.length && <tr><td colSpan={6}>Henüz belge yok.</td></tr>}
                {docs.map((d) => (
                  <tr key={d.id} className="click" onClick={() => open(d)}>
                    <td>
                      <span className="fname">
                        <span className="ftype">{d.type}</span>
                        <span>
                          {d.title} <small>{d.file}{developerMode ? ` · ${d.id}` : ""}</small>
                        </span>
                      </span>
                    </td>
                    <td>
                      <Status status={d.status} />
                    </td>
                    <td>{d.version}</td>
                    <td>{d.pages || "—"}</td>
                    <td className="mono muted">{d.updated}</td>
                    <td>
                      <button
                        className="btn sm" aria-label={`${d.title} belgesini aç`}
                        onClick={(e) => {
                          e.stopPropagation();
                          open(d);
                        }}
                      >
                        Aç
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}
