import { Bricolage_Grotesque, IBM_Plex_Mono } from "next/font/google";

// Homepage-scoped brand faces for the "Open Ledger" marketing look. Loaded
// here rather than in the root layout so the app shell and the (still dark)
// interior marketing pages ship zero extra font bytes; the homepage attaches
// the variables to its own <main>. Body text stays on the layout's Inter.

export const displayFont = Bricolage_Grotesque({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
});

export const brandMonoFont = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-brand-mono",
});
