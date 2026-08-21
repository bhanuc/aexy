import { displayFont, brandMonoFont } from "@/components/landing/fonts";

// Root wrapper for every "Open Ledger" marketing page: attaches the theme
// scope (which also restyles shared previews like McpChatPreview via
// globals.css), the display/mono font variables, and the paper canvas.
// Server component — pages compose it as their outermost element.
//
// A <div>, not a <main>. Pages render <LandingHeader /> and <LandingFooter />
// as children, and ARIA only grants <header> the `banner` role and <footer>
// the `contentinfo` role when they are NOT inside <main>/<article>/<section>.
// Wrapping everything in <main> therefore stripped both landmarks from every
// marketing page while making <main> itself meaningless, since it spanned the
// whole document.
//
// Still missing: a real <main> around each page's content, between the header
// and the footer. That needs a per-page change (38 of them, 8 of which also
// render JSON-LD before the header), so it is deliberately not done here.
export function LedgerPage({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`theme-ledger ${displayFont.variable} ${brandMonoFont.variable} min-h-screen bg-ledger-paper text-ledger-ink antialiased ${className}`}
    >
      {children}
    </div>
  );
}
