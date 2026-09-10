import { Metadata } from "next";

// The parent /tickets layout owns the AppAccessGuard and the title template
// ({ default, template }); this only names the page. A bare string here would
// replace the parent's template object for this subtree and strip " | Aexy".
export const metadata: Metadata = {
  title: "Alerts",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
