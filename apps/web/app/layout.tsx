import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Docgrain Konsolu", description: "Belge operasyonları ve kalite inceleme konsolu" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="tr"><body>{children}</body></html>;
}
