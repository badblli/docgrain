"use client";

import { useEffect, useState } from "react";
import { useDeveloperMode } from "../developer-mode";
import { getCollectionLabel, getFieldLabel } from "./labels";

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
  const [collectionCounts, setCollectionCounts] = useState<Record<string, number | null>>({});
  const [cachedRecords, setCachedRecords] = useState<Record<string, any[]>>({});
  const [selectedCollection, setSelectedCollection] = useState<string | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<any | null>(null);
  const [records, setRecords] = useState<any[]>([]);
  const [showI18n, setShowI18n] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const currentRevision = revisions[0];

  // Revizyon ve koleksiyon listesini getir
  useEffect(() => {
    let canceled = false;
    setState("loading");
    setSelectedRecord(null);

    fetch(`${apiUrl}/v1/workspaces/${workspaceId}/revisions`)
      .then((r) => {
        if (!r.ok) throw new Error("API ulaşılamıyor.");
        return r.json();
      })
      .then((revs: string[]) => {
        if (canceled) return;
        if (!revs || revs.length === 0) {
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
              const cols: string[] = data.collections || [];
              setCollections(cols);
              setState(cols.length === 0 ? "empty" : "loaded");

              // Kartlarda kayıt sayılarını göstermek için koleksiyonları paralel yükle
              if (cols.length > 0) {
                cols.forEach((colName) => {
                  fetch(
                    `${apiUrl}/v1/workspaces/${workspaceId}/revisions/${revs[0]}/collections/${colName}?mode=${mode}`
                  )
                    .then((res) => (res.ok ? res.json() : []))
                    .then((rows: any[]) => {
                      if (canceled) return;
                      const count = Array.isArray(rows) ? rows.length : 0;
                      setCollectionCounts((prev) => ({ ...prev, [colName]: count }));
                      setCachedRecords((prev) => ({ ...prev, [colName]: rows }));
                    })
                    .catch(() => {
                      if (canceled) return;
                      setCollectionCounts((prev) => ({ ...prev, [colName]: 0 }));
                    });
                });
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

  // Seçilen koleksiyonun kayıtlarını güncelle
  useEffect(() => {
    if (!selectedCollection || !currentRevision) return;

    if (cachedRecords[selectedCollection]) {
      setRecords(cachedRecords[selectedCollection]);
      return;
    }

    let canceled = false;
    fetch(
      `${apiUrl}/v1/workspaces/${workspaceId}/revisions/${currentRevision}/collections/${selectedCollection}?mode=${mode}`
    )
      .then((r) => r.json())
      .then((data) => {
        if (canceled) return;
        const rows = Array.isArray(data) ? data : [];
        setRecords(rows);
        setCachedRecords((prev) => ({ ...prev, [selectedCollection]: rows }));
      })
      .catch(() => {
        if (canceled) return;
        setRecords([]);
      });

    return () => {
      canceled = true;
    };
  }, [apiUrl, workspaceId, selectedCollection, currentRevision, mode, cachedRecords]);

  // Seçilen kayıt değiştiğinde veya liste güncellendiğinde senkronize et
  useEffect(() => {
    if (selectedRecord) {
      const updated = records.find((r) => r.id === selectedRecord.id);
      if (updated) {
        setSelectedRecord(updated);
      }
    }
  }, [records]);

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
    setSelectedRecord(null);
    setRecords([]);
    setCachedRecords({});
    setCollectionCounts({});
  };

  const getReviewBadge = (reviewState: string) => {
    switch (reviewState) {
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
    if (val === null || val === undefined) return "—";
    if (Array.isArray(val)) {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
          {val.map((v, i) => (
            <div key={i}>• {String(v)}</div>
          ))}
        </div>
      );
    }
    if (typeof val === "object") {
      return JSON.stringify(val);
    }
    return String(val);
  };

  const EvidenceView = ({ evidence }: { evidence: any[] }) => {
    if (!evidence || evidence.length === 0) return null;
    return (
      <details className="evidence-details" style={{ marginTop: "6px", fontSize: "12px", color: "#666" }}>
        <summary style={{ cursor: "pointer", userSelect: "none" }}>Kaynakta göster</summary>
        <ul style={{ paddingLeft: "16px", marginTop: "4px", marginBottom: "4px" }}>
          {evidence.map((e, idx) => (
            <li key={idx} style={{ marginTop: "4px", overflowWrap: "anywhere" }}>
              <b>{e.document_id}</b> ({e.locator})<br />
              <i style={{ color: "#444" }}>"{e.quote}"</i>
            </li>
          ))}
        </ul>
      </details>
    );
  };

  // Bir kaydın başlığı: 'name', 'title' veya ilk dolu metin alanı
  const getRecordTitle = (record: Record<string, any>): string => {
    if (record.name && typeof record.name === "string") return record.name;
    if (record.title && typeof record.title === "string") return record.title;
    for (const [key, value] of Object.entries(record)) {
      if (key === "id" || key === "_meta" || key === "i18n") continue;
      if (typeof value === "string" && value.trim()) {
        return value;
      }
    }
    return "Kayıt Detayı";
  };

  // Bir kaydın tek satırlık özeti
  const getRecordSummary = (record: Record<string, any>): string => {
    const title = getRecordTitle(record);
    const parts: string[] = [];

    for (const [key, value] of Object.entries(record)) {
      if (key === "id" || key === "_meta" || key === "i18n") continue;
      if (typeof value === "string" && value === title) continue;
      if (value === null || value === undefined || value === "") continue;

      const label = getFieldLabel(key);
      let valStr = "";
      if (Array.isArray(value)) {
        valStr = value.slice(0, 2).map(String).join(", ") + (value.length > 2 ? "..." : "");
      } else if (typeof value === "object") {
        continue;
      } else {
        valStr = String(value);
      }

      if (valStr) {
        parts.push(`${label}: ${valStr}`);
      }
      if (parts.length >= 3) break;
    }

    return parts.length > 0 ? parts.join(" • ") : "Ayrıntı görüntülemek için tıklayın";
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

      <div className="wrap" style={{ minWidth: 0, maxWidth: "100%", boxSizing: "border-box" }}>
        {/* 1. GÖRÜNÜM: Koleksiyon Kartları */}
        {!selectedCollection ? (
          <div className="informationGrid" style={{ minWidth: 0, maxWidth: "100%" }}>
            {collections.map((c) => {
              const count = collectionCounts[c];
              const countText =
                count !== undefined && count !== null ? `${count} kayıt` : "…";

              return (
                <section
                  className="card informationCard click"
                  key={c}
                  onClick={() => {
                    setSelectedCollection(c);
                    setSelectedRecord(null);
                  }}
                  style={{ minWidth: 0, boxSizing: "border-box" }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px" }}>
                    <Icon name="grid" />
                    <span
                      className="pill"
                      style={{
                        fontSize: "11px",
                        background: "#f0f4ed",
                        color: "#42624c",
                        fontWeight: "600",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {countText}
                    </span>
                  </div>
                  <h2 style={{ overflowWrap: "anywhere", wordBreak: "break-word", margin: "16px 0 8px" }}>
                    {getCollectionLabel(c)}
                  </h2>
                  <div className="sub2" style={{ overflowWrap: "anywhere" }}>
                    Kayıtları incelemek için tıklayın
                  </div>
                </section>
              );
            })}
          </div>
        ) : !selectedRecord ? (
          /* 2. GÖRÜNÜM: Koleksiyon İçi Kayıt Listesi */
          <div style={{ minWidth: 0, maxWidth: "100%" }}>
            <div
              style={{
                marginBottom: "16px",
                display: "flex",
                gap: "12px",
                alignItems: "center",
                flexWrap: "wrap",
                minWidth: 0,
              }}
            >
              <button
                className="btn sm"
                onClick={() => {
                  setSelectedCollection(null);
                  setSelectedRecord(null);
                }}
              >
                ← Bilgi Listelerine Dön
              </button>
              <h2 style={{ margin: 0, overflowWrap: "anywhere", wordBreak: "break-word" }}>
                {getCollectionLabel(selectedCollection)}
              </h2>
              <span
                className="pill"
                style={{ fontSize: "12px", background: "#f0f4ed", color: "#42624c" }}
              >
                {records.length} kayıt
              </span>
              <Ep>
                GET /v1/workspaces/{workspaceId}/revisions/{currentRevision}/collections/{selectedCollection}?mode={mode}
              </Ep>
            </div>

            {records.length === 0 ? (
              <EmptyState title="Kayıt yok" text="Bu listede uygun kayıt bulunamadı." />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px", minWidth: 0 }}>
                {records.map((r, i) => {
                  const title = getRecordTitle(r);
                  const summary = getRecordSummary(r);
                  const state = r._meta?.review_state;

                  return (
                    <div
                      key={r.id || i}
                      className="card click"
                      onClick={() => setSelectedRecord(r)}
                      style={{
                        padding: "16px 18px",
                        cursor: "pointer",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: "12px",
                        minWidth: 0,
                        boxSizing: "border-box",
                      }}
                    >
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "8px",
                            flexWrap: "wrap",
                            minWidth: 0,
                          }}
                        >
                          <strong
                            style={{
                              fontSize: "15px",
                              color: "#1f2937",
                              overflowWrap: "anywhere",
                              wordBreak: "break-word",
                            }}
                          >
                            {title}
                          </strong>
                          {state && getReviewBadge(state)}
                          {developerMode && (
                            <code className="ep" style={{ fontSize: "10px" }}>
                              {r.id}
                            </code>
                          )}
                        </div>
                        <div
                          className="sub2"
                          style={{
                            marginTop: "6px",
                            fontSize: "12.5px",
                            color: "#555",
                            overflowWrap: "anywhere",
                            wordBreak: "break-word",
                          }}
                        >
                          {summary}
                        </div>
                      </div>
                      <div
                        style={{
                          color: "var(--muted)",
                          fontSize: "18px",
                          fontWeight: "bold",
                          flexShrink: 0,
                          paddingLeft: "8px",
                        }}
                      >
                        →
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          /* 3. GÖRÜNÜM: Kayıt Detayı */
          <div style={{ minWidth: 0, maxWidth: "100%" }}>
            <div
              style={{
                marginBottom: "16px",
                display: "flex",
                gap: "10px",
                alignItems: "center",
                flexWrap: "wrap",
                minWidth: 0,
              }}
            >
              <button
                className="btn sm"
                onClick={() => setSelectedRecord(null)}
              >
                ← {getCollectionLabel(selectedCollection)} Listesine Dön
              </button>
              <h2 style={{ margin: 0, overflowWrap: "anywhere", wordBreak: "break-word" }}>
                {getRecordTitle(selectedRecord)}
              </h2>
              {selectedRecord._meta?.review_state && getReviewBadge(selectedRecord._meta.review_state)}
              <Ep>
                GET /v1/workspaces/{workspaceId}/revisions/{currentRevision}/collections/{selectedCollection}/records/{selectedRecord.id}?mode={mode}
              </Ep>
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

            <section className="card" style={{ overflowX: "hidden", minWidth: 0, boxSizing: "border-box" }}>
              {developerMode && (
                <div style={{ marginBottom: "14px" }}>
                  <code className="ep">{selectedRecord.id}</code>
                </div>
              )}

              <table
                className="grid"
                style={{
                  tableLayout: "fixed",
                  width: "100%",
                  maxWidth: "100%",
                  boxSizing: "border-box",
                }}
              >
                <tbody>
                  {Object.keys(selectedRecord).map((key) => {
                    if (key === "id" || key === "_meta" || key === "i18n") return null;
                    const meta = selectedRecord._meta?.fields?.[key];
                    const i18nVals = selectedRecord.i18n
                      ? Object.keys(selectedRecord.i18n)
                          .map((lang) => ({
                            lang,
                            val: selectedRecord.i18n[lang][key],
                            state: meta?.i18n_review_state?.[lang],
                          }))
                          .filter((x) => x.val !== undefined)
                      : [];

                    return (
                      <tr key={key}>
                        <td
                          style={{
                            width: "35%",
                            fontWeight: "bold",
                            wordBreak: "break-word",
                            overflowWrap: "anywhere",
                            color: "#374151",
                            verticalAlign: "top",
                            padding: "10px 12px",
                          }}
                        >
                          {getFieldLabel(key)}
                          {developerMode && (
                            <div style={{ fontSize: "10px", color: "var(--muted)", fontWeight: "normal", marginTop: "2px" }}>
                              {key}
                            </div>
                          )}
                        </td>
                        <td
                          style={{
                            wordBreak: "break-word",
                            overflowWrap: "anywhere",
                            verticalAlign: "top",
                            padding: "10px 12px",
                          }}
                        >
                          <div>
                            {renderValue(selectedRecord[key])}
                            {meta?.review_state && (
                              <span style={{ marginLeft: "8px" }}>
                                {getReviewBadge(meta.review_state)}
                              </span>
                            )}
                            {meta?.evidence && <EvidenceView evidence={meta.evidence} />}
                          </div>

                          {showI18n &&
                            i18nVals.map((i18nVal) => (
                              <div
                                key={i18nVal.lang}
                                style={{
                                  marginTop: "8px",
                                  padding: "8px 10px",
                                  background: "#f9f9f9",
                                  borderRadius: "4px",
                                  border: "1px solid #eee",
                                }}
                              >
                                <span
                                  style={{
                                    fontWeight: "bold",
                                    marginRight: "8px",
                                    textTransform: "uppercase",
                                    fontSize: "0.8em",
                                    color: "#4b5563",
                                  }}
                                >
                                  {i18nVal.lang}:
                                </span>
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
                  <summary className="mono muted" style={{ cursor: "pointer" }}>
                    Geliştirici: Ham JSON
                  </summary>
                  <pre
                    style={{
                      padding: "10px",
                      background: "#f5f5f5",
                      overflowX: "auto",
                      fontSize: "11px",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-all",
                      maxWidth: "100%",
                      borderRadius: "4px",
                      marginTop: "8px",
                    }}
                  >
                    {JSON.stringify(selectedRecord, null, 2)}
                  </pre>
                </details>
              )}
            </section>
          </div>
        )}
      </div>
    </>
  );
}
