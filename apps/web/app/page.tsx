"use client";

import { useEffect, useState } from "react";

type Document = { type: string; title: string; file: string; status: "done" | "running" | "partial" | "failed"; version: string; pages: string; chunks: string; updated: string };

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

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/v1/documents?limit=50`)
      .then((response) => {
        if (!response.ok) throw new Error("API yanıt vermedi");
        return response.json();
      })
      .then((payload: Array<{ document: { title: string; filename: string; updated_at: string }; latest_version?: { status: string; revision?: number; page_count?: number; chunk_count?: number } | null }>) => {
        setItems(payload.map(({ document, latest_version }) => ({
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
        <div className="intro"><div><p className="eyebrow">ÇALIŞMA ALANI</p><h1>Dokümanlar</h1><p className="description">Belgelerini, sürümlerini ve çıkarılan içerikleri tek bir yerde incele.</p></div><button className="primaryButton">＋ Yükle</button></div>
        <div className="subnav"><a className="selected" href="#all">Tümü <span>6</span></a><a href="#recent">Son kullanılanlar</a><a href="#failed">İnceleme bekleyenler <span className="alertCount">2</span></a><div className="subnavEnd"><button className="viewButton" aria-label="Liste görünümü">☷</button><button className="viewButton" aria-label="Izgara görünümü">⊞</button></div></div>
        <div className="documentList" id="documents"><div className="listHeader"><span>AD</span><span>DURUM</span><span>GÜNCELLENME</span><span /></div>{loading ? <div className="loadingRow">Dokümanlar yükleniyor…</div> : items.map((doc) => <a className="documentRow" href={`#${doc.file}`} key={doc.file}><div className="documentName"><span className={`fileIcon ${doc.type.toLowerCase()}`}>{doc.type === "DOCX" ? "W" : doc.type === "XLSX" ? "X" : "P"}</span><span><strong>{doc.title}</strong><small>{doc.file} · {doc.version} · {doc.pages} sayfa</small></span></div><span className={`status ${doc.status}`}><i />{statusLabel[doc.status]}{doc.status === "partial" && <small>{doc.chunks} chunk</small>}</span><time>{doc.updated}</time><span className="rowArrow">→</span></a>)}</div>
        <div className="emptyHint"><span>✦</span><p>Yeni bir doküman yükleyerek başlayın.<br /><small>İşleme alındığında sürümler ve içerik detayları burada görünür.</small></p><button className="outlineButton">Doküman yükle</button></div>
        <footer><span>Docgrain</span><span>API bağlı · v0.0.1</span></footer>
      </div>
    </section>
  </main>;
}
