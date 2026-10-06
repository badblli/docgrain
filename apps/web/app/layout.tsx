import type { Metadata } from "next";
import "./globals.css";
import "./screens.css";

export const metadata: Metadata = { title: "Docgrain Konsolu", description: "Şirketinizin belgeleri, soruları ve koleksiyonları." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="tr"><body>{children}</body></html>;
}
