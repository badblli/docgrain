import { useDeveloperMode } from "./developer-mode";

export function Icon({ name }: { name: string }) {
  const p: Record<string, React.ReactNode> = {
    summary: <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 9h8M8 13h3M8 16h6" /></>,
    question: <><path d="M9 8a3 3 0 0 1 6 0c0 2-3 2-3 4M12 16h.01" /><circle cx="12" cy="12" r="9" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    rooms: <><path d="M3 18v-8m18 8v-6H3m2-2V6h14v6M7 9h3m4 0h3" /></>,
    outlets: <><path d="M7 3v7m-3-7v5a3 3 0 0 0 6 0V3M7 11v10M20 3c-4 1-5 6-5 10h5V3Zm0 10v8" /></>,
    activities: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1" /></>,
    doc: (
      <>
        <path d="M6 2.75h8l4 4V21.25H6z" />
        <path d="M14 2.75v4h4M9 11h6M9 15h6" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 7.5V12l3 2" />
      </>
    ),
    grid: (
      <>
        <rect x="4" y="4" width="6" height="6" />
        <rect x="14" y="4" width="6" height="6" />
        <rect x="4" y="14" width="6" height="6" />
        <rect x="14" y="14" width="6" height="6" />
      </>
    ),
    book: (
      <>
        <path d="M5 4h6a3 3 0 0 1 3 3v13H8a3 3 0 0 0-3 1z" />
        <path d="M19 4h-2a3 3 0 0 0-3 3v13h3a3 3 0 0 1 2 1z" />
      </>
    ),
    upload: (
      <>
        <path d="M12 16V4M7.5 8.5 12 4l4.5 4.5" />
        <path d="M4 14v6h16v-6" />
      </>
    ),
  };
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {p[name]}
    </svg>
  );
}
export function Ep({ children }: { children: React.ReactNode }) {
  return useDeveloperMode() ? <code className="ep">{children}</code> : null;
}
export function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="wrap">
      <section className="card emptyArtifact">
        <span>◇</span>
        <h2>{title}</h2>
        <p>{text}</p>
      </section>
    </div>
  );
}
export function Head({
  section = "Çalışma alanı",
  title,
  sub,
  endpoint,
  children,
}: {
  section?: string;
  title: string;
  sub: string;
  endpoint: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="head">
      <div className="crumb">
        <span>{section}</span>
        <b>›</b>
        <span>{title}</span>
      </div>
      <div className="h1row">
        <div>
          <h1>{title}</h1>
          <p className="sub">{sub}</p>
        </div>
        <div className="headact">
          {children}
          {endpoint && <Ep>{endpoint}</Ep>}
        </div>
      </div>
    </header>
  );
}

