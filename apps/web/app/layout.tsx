import type { Metadata } from "next";
import "../../../docs/brand/tokens.css";
import "./globals.css";
import "./screens.css";

export const metadata: Metadata = {
  title: "Docgrain", description: "Şirketinizin belgeleri, soruları ve koleksiyonları.",
  icons: {
    icon: { url: "/brand/favicon.svg", type: "image/svg+xml" },
    apple: { url: "/brand/logo-mark.svg", type: "image/svg+xml" },
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="tr"><body>{children}</body></html>;
}
