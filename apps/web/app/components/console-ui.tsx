import { ArrowRight, BedDouble, BookOpen, Check, Clock3, FileText, HelpCircle, LayoutGrid, NotebookText, Sun, Upload, Utensils, type LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { useDeveloperMode } from "./developer-mode";

const icons: Record<string, LucideIcon> = {
  summary: NotebookText, question: HelpCircle, check: Check, arrow: ArrowRight,
  rooms: BedDouble, outlets: Utensils, activities: Sun, doc: FileText,
  clock: Clock3, grid: LayoutGrid, book: BookOpen, upload: Upload,
};
export function Icon({ name, className = "size-4 shrink-0" }: { name: string; className?: string }) {
  const Component = icons[name] ?? FileText;
  return <Component className={className} strokeWidth={1.6} aria-hidden="true" />;
}
/** Shared side padding for every console screen: 16 px phone, 24 px tablet, 40 px desktop. */
export const pageGutter = "px-4 md:px-6 xl:px-10";
/** Full-width screen body next to the sidebar; content is left-aligned with the page header. */
export const pageBody = "flex w-full min-w-0 flex-col gap-6 px-4 pb-16 pt-6 md:gap-8 md:px-6 xl:px-10";
/** Card grid that adds columns as the main area grows (1 on phones, up to 5 at 1920 px). */
export const cardGrid = "grid grid-cols-[repeat(auto-fill,minmax(min(100%,17rem),1fr))] gap-4";
export function Ep({ children }: { children: React.ReactNode }) {
  return useDeveloperMode() ? <code className="max-w-full overflow-x-auto rounded-sm border border-line bg-sheet px-2 py-1 font-mono text-2xs text-muted">{children}</code> : null;
}
export function EmptyState({ title, text }: { title: string; text: string }) {
  return <div className="flex w-full min-w-0 flex-col gap-6 px-4 py-6 md:px-6 xl:px-10">
    <Card className="items-center gap-3 border border-dashed border-line-strong p-10 text-center ring-0">
      <span className="grid size-9 place-items-center rounded-full bg-sheet text-muted"><Icon name="doc" className="size-5" /></span>
      <h2 className="text-md font-semibold">{title}</h2>
      <p className="max-w-[48ch] text-sm text-muted">{text}</p>
    </Card>
  </div>;
}
export function Head({ section = "Çalışma alanı", title, sub, endpoint, children }: {
  section?: string; title: string; sub: string; endpoint: string; children?: React.ReactNode;
}) {
  return <header className="w-full min-w-0 px-4 pt-6 md:px-6 md:pt-10 xl:px-10">
    <span className="sr-only">{section}</span>
    <div className="flex flex-wrap items-start gap-3">
      <div className="min-w-0 flex-1"><h1 className="text-2xl font-semibold tracking-[-0.035em] text-balance wrap-anywhere">{title}</h1>
        <p className="mt-1 max-w-[74ch] text-base text-muted wrap-anywhere">{sub}</p></div>
      {(children || endpoint) && <div className="flex max-w-full flex-wrap items-center gap-2">{children}{endpoint && <Ep>{endpoint}</Ep>}</div>}
    </div>
  </header>;
}
