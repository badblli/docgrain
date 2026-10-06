import type { Metadata } from "next";
import { Instrument_Sans, Source_Serif_4, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const uiFont = Instrument_Sans({ subsets: ["latin", "latin-ext"], variable: "--font-instrument", display: "swap" });
const documentFont = Source_Serif_4({ subsets: ["latin", "latin-ext"], variable: "--font-source-serif", display: "swap" });
const monoFont = JetBrains_Mono({ subsets: ["latin", "latin-ext"], variable: "--font-jetbrains", display: "swap" });

export const metadata: Metadata = {
  title: "Docgrain", description: "Şirketinizin belgeleri, soruları ve koleksiyonları.",
  icons: {
    icon: { url: "/brand/favicon.svg", type: "image/svg+xml" },
    apple: { url: "/brand/logo-mark.svg", type: "image/svg+xml" },
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="tr" className={`${uiFont.variable} ${documentFont.variable} ${monoFont.variable}`}><body>{children}</body></html>;
}
