"use client";

import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";

type Document = { id?: string; versionId?: string; type: string; title: string; file: string; status: "done" | "running" | "partial" | "failed"; version: string; pages: string; chunks: string; updated: string };

const documents: Document[] = [
  { type: "PDF", title: "Finansal İstikrar Raporu 2025-II", file: "fsr-2025-2.pdf", status: "done", version: "v2", pages: "48", chunks: "44", updated: "30 Ağu 2025" },
  { type: "DOCX", title: "Luwi Müşteri Sözleşmesi", file: "sozlesme-v3.docx", status: "done", version: "v1", pages: "12", chunks: "19", updated: "30 Ağu 2025" },
  { type: "PDF", title: "Ürün Kataloğu 2026", file: "katalog-2026.pdf", status: "running", version: "v1", pages: "132", chunks: "—", updated: "31 Ağu 2025" },
  { type: "PDF", title: "Saha Denetim Formu (taranmış)", file: "denetim-2025-08.pdf", status: "partial", version: "v1", pages: "6", chunks: "7", updated: "29 Ağu 2025" },
  { type: "XLSX", title: "Q3 Bütçe Tabloları", file: "q3-butce.xlsx", status: "done", version: "v2", pages: "4", chunks: "11", updated: "28 Ağu 2025" },
  { type: "PDF", title: "Bozuk Tarama", file: "bozuk-dosya.pdf", status: "failed", version: "—", pages: "—", chunks: "—", updated: "27 Ağu 2025" },
];

const statusLabel = { done: "Tamamlandı", running: "İşleniyor", partial: "Kısmi", failed: "Başarısız" };

export default function Home() {
  const [items, setItems] = useState<Document[]>(documents);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [selected, setSelected] = useState<Document | null>(null);
  const [artifact, setArtifact] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const loadDocuments = useCallback(() => {
    setLoading(true);
    fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/v1/documents?limit=50`)
      .then((response) => {
        if (!response.ok) throw new Error("API yanıt vermedi");
        return response.json();
      })
      .then((payload: Array<{ document: { id: string; title: string; filename: string; updated_at: string }; latest_version?: { id: string; status: string; revision?: number; page_count?: number; chunk_count?: number } | null }>) => {
        setItems(payload.map(({ document, latest_version }) => ({
          id: document.id,
          versionId: latest_version?.id,
          type: document.filename.split(".").pop()?.toUpperCase() ?? "DOC",
          title: document.title,
          file: document.filename,
          status: latest_version?.status === "done" ? "done" : latest_version?.status === "partial" ? "partial" : latest_version?.status === "failed" ? "failed" : "running",
          version: latest_version ? `v${latest_version.revision ?? 1}` : "—",
          pages: latest_version?.page_count?.toString() ?? "—",
          chunks: latest_version?.chunk_count?.toString() ?? "—",
          updated: new Date(document.updated_at).toLocaleDateString("tr-TR", { day: "2-digit", month: "short", year: "numeric" }),
        })));
      })
      .catch(() => setError("API bağlantısı kurulamadı; demo verisi gösteriliyor."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadDocuments(); }, [loadDocuments]);

  async function handleFile(file: File) {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    setUploading(true);
    setUploadMessage(null);
    setError(null);
    try {
      const registration = await fetch(`${apiUrl}/v1/documents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_id: "ws_luwi", filename: file.name, mime_type: file.type || "application/octet-stream", byte_size: file.size }),
      });
      if (!registration.ok) throw new Error("Kayıt oluşturulamadı");
      const intent = await registration.json();
      const data = new FormData();
      data.append("file", file);
      const stored = await fetch(intent.upload_url, { method: "PUT", body: data });
      if (!stored.ok) throw new Error("Dosya depoya yazılamadı");
      const confirmation = await fetch(`${apiUrl}/v1/documents/${intent.document.id}/versions/${intent.version.id}/uploaded`, { method: "POST" });
      if (!confirmation.ok) throw new Error("Yükleme doğrulanamadı");
      setUploadMessage(`${file.name} kuyruğa alındı.`);
      loadDocuments();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Yükleme tamamlanamadı");
    } finally {
      setUploading(false);
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void handleFile(file);
    event.target.value = "";
  }

  async function openDocument(doc: Document) {
    setSelected(doc);
    setArtifact(null);
    setArtifactError(null);
    if (doc.status !== "done" || !doc.id || !doc.versionId) return;
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const response = await fetch(`${apiUrl}/v1/documents/${doc.id}/versions/${doc.versionId}/artifacts/document.md`);
      if (!response.ok) throw new Error("Canonical içerik henüz hazır değil.");
      setArtifact(await response.text());
    } catch (reason) {
      setArtifactError(reason instanceof Error ? reason.message : "İçerik açılamadı.");
    }
  }

  return <main className="appShell">
    <aside className="sidebar" aria-label="Ana navigasyon">
      <a className="wordmark" href="#top"><span className="wordmarkIcon">d</span><span>docgrain</span></a>
      <div className="workspacePicker"><span className="workspaceAvatar">L</span><span><b>Luwi çalışma alanı</b><small>Özel alan</small></span><span className="chevron">⌄</span></div>
      <nav className="navGroup"><a className="navItem active" href="#documents"><span>▦</span> Dokümanlar <em>6</em></a><a className="navItem" href="#jobs"><span>◷</span> İşler <em>1</em></a><a className="navItem" href="#providers"><span>◌</span> Sağlayıcılar</a></nav>
      <div className="sidebarSection"><p>REFERANS</p><a className="navItem" href="/docs"><span>⌘</span> Veri sözleşmesi</a></div>
      <div className="sidebarBottom"><a href="#help">Yardım &amp; geri bildirim</a><div className="userRow"><span className="userAvatar">L</span><span>Lenovo</span><span className="more">•••</span></div></div>
    </aside>
    <section className="workspace" id="top">
      <header className="topbar"><div className="breadcrumbs"><span>Çalışma alanı</span><b>/</b><strong>Dokümanlar</strong></div><div className="topbarActions"><button className="searchButton" aria-label="Ara">⌕ <span>Ara</span><kbd>Ctrl K</kbd></button><button className="quietButton" aria-label="Bildirimler">♧</button><span className="connection"><i /> bağlı</span></div></header>
      <div className="content">
        {error && <div className="apiNotice" role="status">{error}</div>}
        {uploadMessage && <div className="uploadNotice" role="status">{uploadMessage}</div>}
        <input ref={fileInput} style={{ display: "none" }} type="file" accept=".pdf,.docx,.pptx,.xlsx,.html,.txt" onChange={onFileChange} />
        <div className="intro"><div><p className="eyebrow">ÇALIŞMA ALANI</p><h1>Dokümanlar</h1><p className="description">Belgelerini, sürümlerini ve çıkarılan içerikleri tek bir yerde incele.</p></div><button className="primaryButton" onClick={() => fileInput.current?.click()} disabled={uploading}>{uploading ? "Yükleniyor…" : "＋ Yükle"}</button></div>
        <div className="subnav"><a className="selected" href="#all">Tümü <span>{items.length}</span></a><a href="#recent">Son kullanılanlar</a><a href="#failed">İnceleme bekleyenler <span className="alertCount">2</span></a><div className="subnavEnd"><button className="viewButton" aria-label="Liste görünümü">☷</button><button className="viewButton" aria-label="Izgara görünümü">⊞</button></div></div>
        <div className="documentList" id="documents"><div className="listHeader"><span>AD</span><span>DURUM</span><span>GÜNCELLENME</span><span /></div>{loading ? <div className="loadingRow">Dokümanlar yükleniyor…</div> : items.map((doc) => <button className={`documentRow ${selected?.id === doc.id ? "selectedRow" : ""}`} type="button" onClick={() => void openDocument(doc)} key={doc.id ?? doc.file}><div className="documentName"><span className={`fileIcon ${doc.type.toLowerCase()}`}>{doc.type === "DOCX" ? "W" : doc.type === "XLSX" ? "X" : "P"}</span><span><strong>{doc.title}</strong><small>{doc.file} · {doc.version} · {doc.pages} sayfa</small></span></div><span className={`status ${doc.status}`}><i />{statusLabel[doc.status]}{doc.status === "partial" && <small>{doc.chunks} chunk</small>}</span><time>{doc.updated}</time><span className="rowArrow">→</span></button>)}</div>
        {selected && <section className="artifactPanel" aria-live="polite"><div className="artifactHeader"><div><p className="eyebrow">CANONICAL ARTIFACT</p><h2>{selected.title}</h2><small>{selected.status === "done" ? "Docling Markdown çıktısı" : "İş tamamlanınca içerik burada açılır."}</small></div><button className="quietButton" onClick={() => setSelected(null)} aria-label="İçeriği kapat">×</button></div>{artifactError && <p className="artifactState">{artifactError}</p>}{selected.status === "done" && !artifact && !artifactError && <p className="artifactState">Canonical içerik yükleniyor…</p>}{artifact && <pre className="artifactContent">{artifact}</pre>}</section>}
        <div className="emptyHint"><span>✦</span><p>Yeni bir doküman yükleyerek başlayın.<br /><small>İşleme alındığında sürümler ve içerik detayları burada görünür.</small></p><button className="outlineButton" onClick={() => fileInput.current?.click()} disabled={uploading}>Doküman yükle</button></div>
        <footer><span>Docgrain</span><span>API bağlı · v0.0.1</span></footer>
      </div>
    </section>
  </main>;
}
