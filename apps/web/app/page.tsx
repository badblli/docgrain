type Document = { type: string; title: string; file: string; status: "done" | "running" | "partial" | "failed"; version: string; pages: string; chunks: string; updated: string };

const documents: Document[] = [
  { type: "PDF", title: "Finansal İstikrar Raporu 2025-II", file: "fsr-2025-2.pdf", status: "done", version: "v2", pages: "48", chunks: "44", updated: "30 Ağu 2025, 14:06" },
  { type: "DOCX", title: "Luwi Müşteri Sözleşmesi", file: "sozlesme-v3.docx", status: "done", version: "v1", pages: "12", chunks: "19", updated: "30 Ağu 2025, 11:22" },
  { type: "PDF", title: "Ürün Kataloğu 2026", file: "katalog-2026.pdf", status: "running", version: "v1", pages: "132", chunks: "—", updated: "31 Ağu 2025, 10:58" },
  { type: "PDF", title: "Saha Denetim Formu (taranmış)", file: "denetim-2025-08.pdf", status: "partial", version: "v1", pages: "6", chunks: "7", updated: "29 Ağu 2025, 16:41" },
  { type: "XLSX", title: "Q3 Bütçe Tabloları", file: "q3-butce.xlsx", status: "done", version: "v2", pages: "4", chunks: "11", updated: "28 Ağu 2025, 09:15" },
  { type: "PDF", title: "Bozuk Tarama", file: "bozuk-dosya.pdf", status: "failed", version: "—", pages: "—", chunks: "—", updated: "27 Ağu 2025, 18:03" },
];

const statusLabel = { done: "tamamlandı", running: "çalışıyor", partial: "kısmi", failed: "başarısız" };

export default function Home() {
  return <main className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brandMark">✦</span><span>docgrain</span><small>KONSOL</small></div>
      <p className="navLabel">ÇALIŞMA ALANI</p>
      <nav><a className="active" href="#documents"><span>▦</span> Dokümanlar <b>6</b></a><a href="#jobs"><span>◷</span> İşler <b>1</b></a><a href="#providers"><span>◌</span> Sağlayıcılar</a></nav>
      <p className="navLabel reference">REFERANS</p><a className="referenceLink" href="/docs"><span>⌘</span> Veri sözleşmesi</a>
      <div className="sidebarFoot"><span className="dot" /> Prototip · sahte veri <span className="api">/v1</span></div>
    </aside>
    <section className="content">
      <header className="topbar"><div className="crumb">Çalışma alanı <span>›</span> Dokümanlar</div><div className="topActions"><span className="online"><i /> API bağlı</span><button className="avatar">L</button></div></header>
      <div className="pageHead"><div><div className="eyebrow">ÇALIŞMA ALANI</div><h1>Dokümanlar</h1><p>Yüklenen her dosya bir doküman, her yeni içerik özeti (hash) o dokümanın yeni bir sürümü olur. Eski sürümler asla değişmez.</p></div><button className="primary">＋ Doküman yükle</button></div>
      <div className="contract"><span className="method">GET</span><code>/v1/documents</code><span>API sözleşmesine göre çizildi; her başlıktaki mavi rozet o ekranı besleyen uç noktadır.</span></div>
      <section className="uploadCard"><div className="uploadIcon">↥</div><div><h2>Doküman yükle veya bir kaynak kaydet</h2><p>PDF, DOCX, PPTX, XLSX, HTML. Dosya nesne depolamaya olduğu gibi yazılır, hash&apos;i alınır ve dayanıklı bir iş kuyruğa girer.</p></div><button className="ghost">Örnek PDF&apos;i işle <span>→</span></button></section>
      <div className="tableHead"><div><h2>Tüm dokümanlar</h2><p>Satıra tıkla → sürüm, pipeline ve çıkarılan içerik.</p></div><div className="filters"><button className="filter">Tüm durumlar⌄</button><button className="filter">↕ Son işlem</button></div></div>
      <div className="contract mini"><span className="method">GET</span><code>/v1/documents?limit=50</code></div>
      <div className="tableWrap"><table><thead><tr><th>DOKÜMAN</th><th>DURUM</th><th>SÜRÜM</th><th>SAYFA</th><th>CHUNK</th><th>SON İŞLEM</th><th /></tr></thead><tbody>{documents.map((doc) => <tr key={doc.file} className="row"><td><div className="docCell"><span className={`fileType ${doc.type.toLowerCase()}`}>{doc.type}</span><div><strong>{doc.title}</strong><small>{doc.file}</small></div></div></td><td><span className={`status ${doc.status}`}><i />{statusLabel[doc.status]}</span></td><td>{doc.version}</td><td>{doc.pages}</td><td className={doc.chunks === "—" ? "muted" : ""}>{doc.chunks}</td><td className="date">{doc.updated}</td><td><button className="open">Aç <span>→</span></button></td></tr>)}</tbody></table></div>
      <footer>Docgrain · veri sözleşmesi v0.0.1 <span>Son senkronizasyon: şimdi</span></footer>
    </section>
  </main>;
}
