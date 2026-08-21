import { displayFont, brandMonoFont } from "@/components/landing/fonts";

// Root wrapper for every "Open Ledger" marketing page: attaches the theme
// scope (which also restyles shared previews like McpChatPreview via
// globals.css), the display/mono font variables, and the paper canvas.
// Server component — pages compose it as their outermost element.
export function LedgerPage({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <main
      className={`theme-ledger ${displayFont.variable} ${brandMonoFont.variable} min-h-screen bg-ledger-paper text-ledger-ink antialiased ${className}`}
    >
      {children}
    </main>
  );
}
