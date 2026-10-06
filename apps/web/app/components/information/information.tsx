"use client";

import { useEffect, useState } from "react";
import { useDeveloperMode } from "../developer-mode";

const localizedCollectionNames: Record<string, string> = {
  rooms: "Odalar",
  outlets: "Mekanlar (Restoran/Bar)",
  activities: "Etkinlikler",
  meeting_rooms: "Toplantı Odaları",
  services: "Hizmetler ve Fiyatlar",
  policies: "Kurallar ve Politikalar",
  contact: "İletişim",
};

export function InformationView({
  apiUrl,
  workspaceId,
  Icon,
  Ep,
  Head,
  EmptyState,
}: {
  apiUrl: string;
  workspaceId: string;
  Icon: (props: { name: string }) => React.ReactElement;
  Ep: (props: { children: React.ReactNode }) => React.ReactElement | null;
  Head: (props: {
    section?: string;
    title: string;
    sub: string;
    endpoint: string;
    children?: React.ReactNode;
  }) => React.ReactElement;
  EmptyState: (props: { title: string; text: string }) => React.ReactElement;
}) {
  const developerMode = useDeveloperMode();
  const [mode, setMode] = useState<"preview" | "approved">("preview");
  const [state, setState] = useState<
    "loading" | "error" | "empty" | "loaded"
  >("loading");
  const [revisions, setRevisions] = useState<string[]>([]);
  const [collections, setCollections] = useState<string[]>([]);
  const [selectedCollection, setSelectedCollection] = useState<string | null>(null);
  const [records, setRecords] = useState<any[]>([]);
  const [showI18n, setShowI18n] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const currentRevision = revisions[0];

  useEffect(() => {
    let canceled = false;
    setState("loading");
    fetch(`${apiUrl}/v1/workspaces/${workspaceId}/revisions`)
      .then((r) => {
        if (!r.ok) throw new Error("API ulaşılamıyor.");
        return r.json();
      })
      .then((revs: string[]) => {
        if (canceled) return;
        if (revs.length === 0) {
          setState("empty");
        } else {
          setRevisions(revs);
          return fetch(
            `${apiUrl}/v1/workspaces/${workspaceId}/revisions/${revs[0]}/collections?mode=${mode}`
          )
            .then((r) => {
              if (!r.ok) throw new Error("Bilgi listesi alınamadı.");
              return r.json();
            })
            .then((data: any) => {
              if (canceled) return;
              setCollections(data.collections || []);
              setState("loaded");
              if (!data.collections || data.collections.length === 0) {
                setState("empty");
              }
            });
        }
      })
      .catch((err) => {
        if (canceled) return;
        setErrorMsg(err.message);
        setState("error");
      });
    return () => {
      canceled = true;
    };
  }, [apiUrl, workspaceId, mode]);

  useEffect(() => {
    if (!selectedCollection || !currentRevision) return;
    let canceled = false;
    fetch(
      `${apiUrl}/v1/workspaces/${workspaceId}/revisions/${currentRevision}/collections/${selectedCollection}?mode=${mode}`
    )
      .then((r) => r.json())
      .then((data) => {
        if (canceled) return;
        setRecords(data || []);
      })
      .catch(() => {
         if (canceled) return;
         setRecords([]);
      });
    return () => {
      canceled = true;
    };
  }, [apiUrl, workspaceId, selectedCollection, currentRevision, mode]);

  if (state === "loading") {
    return (
      <>
        <Head title="Bilgi" sub="Belgelerinizden derlenen bilgiler" endpoint="" />
        <div className="wrap">Yükleniyor...</div>
      </>
    );
  }

  if (state === "error") {
    return (
      <>
        <Head title="Bilgi" sub="Belgelerinizden derlenen bilgiler" endpoint="" />
        <EmptyState title="Bağlantı Hatası" text={errorMsg || "API ulaşılamıyor."} />
      </>
    );
  }

  if (state === "empty") {
    return (
      <>
        <Head title="Bilgi" sub="Belgelerinizden derlenen bilgiler" endpoint="" />
        <EmptyState
          title="Henüz veri yok"
          text="Yayınlanmış bir bilgi listesi bulunamadı."
        />
      </>
    );
  }

  const handleModeChange = () => {
    setMode(mode === "preview" ? "approved" : "preview");
    setSelectedCollection(null);
    setRecords([]);
  };

  const getReviewBadge = (state: string) => {
    switch (state) {
      case "proposed":
        return <span className="pill p-warn"><i className="dot"/>Öneri</span>;
      case "needs_review":
        return <span className="pill p-run"><i className="dot"/>İnceleme bekliyor</span>;
      case "accepted":
        return <span className="pill p-ok"><i className="dot"/>Onaylandı</span>;
      default:
        return null;
    }
  };

  const renderValue = (val: any) => {
    if (Array.isArray(val)) {
      return val.map((v, i) => <div key={i}>• {v}</div>);
    }
    return String(val);
  };

  const EvidenceView = ({ evidence }: { evidence: any[] }) => {
    if (!evidence || evidence.length === 0) return null;
    return (
      <details className="evidence-details" style={{ marginTop: "4px", fontSize: "12px", color: "#666" }}>
        <summary style={{ cursor: "pointer", userSelect: "none" }}>Kaynakta göster</summary>
        <ul style={{ paddingLeft: "16px", marginTop: "4px" }}>
          {evidence.map((e, idx) => (
            <li key={idx}>
              <b>{e.document_id}</b> ({e.locator})<br />
              <i>"{e.quote}"</i>
            </li>
          ))}
        </ul>
      </details>
    );
  };

  return (
    <>
      <Head
        title="Bilgi"
        sub="Belgelerinizden derlenen bilgileri burada bulabilirsiniz."
        endpoint={currentRevision ? `GET /v1/workspaces/${workspaceId}/revisions/${currentRevision}/collections` : ""}
      >
        <label className="switch modeSwitch">
          <input
            type="checkbox"
            role="switch"
            checked={mode === "approved"}
            onChange={handleModeChange}
          />
          Onaylı / Önizleme (Şu an: {mode === "preview" ? "Önizleme" : "Onaylı"})
        </label>
      </Head>

      <div className="wrap">
        {!selectedCollection ? (
          <div className="informationGrid">
            {collections.map((c) => (
              <section
                className="card informationCard click"
                key={c}
                onClick={() => setSelectedCollection(c)}
              >
                <Icon name="grid" />
                <h2>{localizedCollectionNames[c] || c}</h2>
                <div style={{ marginTop: "10px" }} className="sub2">Tıklayarak kayıtları görün</div>
              </section>
            ))}
          </div>
        ) : (
          <div>
            <div style={{ marginBottom: "16px", display: "flex", gap: "10px", alignItems: "center" }}>
              <button className="btn sm" onClick={() => setSelectedCollection(null)}>
                ← Geri dön
              </button>
              <h2>{localizedCollectionNames[selectedCollection] || selectedCollection}</h2>
              <Ep>GET /v1/workspaces/{workspaceId}/revisions/{currentRevision}/collections/{selectedCollection}?mode={mode}</Ep>
              <div style={{ flex: 1 }}></div>
              <label className="switch">
                <input
                  type="checkbox"
                  role="switch"
                  checked={showI18n}
                  onChange={(e) => setShowI18n(e.target.checked)}
                />
                Diller
              </label>
            </div>

            {records.length === 0 ? (
              <EmptyState title="Kayıt yok" text="Bu listede uygun kayıt bulunamadı." />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                {records.map((r, i) => (
                  <section className="card" key={r.id || i} style={{ overflowX: "hidden" }}>
                    {developerMode && (
                      <div style={{ marginBottom: "10px" }}>
                        <code className="ep">{r.id}</code>
                      </div>
                    )}
                    <table className="grid" style={{ tableLayout: "fixed", width: "100%" }}>
                      <tbody>
                        {Object.keys(r).map((key) => {
                          if (key === "id" || key === "_meta" || key === "i18n") return null;
                          const meta = r._meta?.fields?.[key];
                          const i18nVals = r.i18n ? Object.keys(r.i18n).map(lang => ({
                            lang,
                            val: r.i18n[lang][key],
                            state: meta?.i18n_review_state?.[lang]
                          })).filter(x => x.val !== undefined) : [];

                          return (
                            <tr key={key}>
                              <td style={{ width: "30%", fontWeight: "bold", wordBreak: "break-word" }}>{key}</td>
                              <td style={{ wordBreak: "break-word" }}>
                                <div>
                                  {renderValue(r[key])}
                                  {meta?.review_state && (
                                    <span style={{ marginLeft: "8px" }}>
                                      {getReviewBadge(meta.review_state)}
                                    </span>
                                  )}
                                  {meta?.evidence && <EvidenceView evidence={meta.evidence} />}
                                </div>
                                
                                {showI18n && i18nVals.map(i18nVal => (
                                  <div key={i18nVal.lang} style={{ marginTop: "8px", padding: "8px", background: "#f9f9f9", borderRadius: "4px" }}>
                                    <span style={{ fontWeight: "bold", marginRight: "8px", textTransform: "uppercase", fontSize: "0.8em" }}>{i18nVal.lang}:</span>
                                    {renderValue(i18nVal.val)}
                                    {i18nVal.state && (
                                      <span style={{ marginLeft: "8px" }}>
                                        {getReviewBadge(i18nVal.state)}
                                      </span>
                                    )}
                                  </div>
                                ))}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    {developerMode && (
                      <details style={{ marginTop: "16px" }}>
                        <summary className="mono muted" style={{ cursor: "pointer" }}>Geliştirici: Ham JSON</summary>
                        <pre style={{ padding: "10px", background: "#f5f5f5", overflowX: "auto", fontSize: "11px" }}>
                          {JSON.stringify(r, null, 2)}
                        </pre>
                      </details>
                    )}
                  </section>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
