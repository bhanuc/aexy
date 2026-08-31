import { NextRequest, NextResponse } from "next/server";

const SUPPORTED_LOCALES = ["en", "hi"];
const DEFAULT_LOCALE = "en";

// Prefixes whose pages render auth-required UI (workspace shell, settings,
// admin tools). The Next.js App Router uses route *groups* in parentheses
// `(app)`/`(admin)` that do NOT appear in URLs, so we list the concrete
// top-level paths their children mount under.
const AUTH_REQUIRED_PREFIXES = [
  "/dashboard",
  "/admin",
  "/agents",
  "/analytics",
  "/audit",
  "/automations",
  "/billing",
  "/calendar",
  "/code-insights",
  "/compliance",
  "/crm",
  "/databases",
  "/dependencies",
  "/docs",
  "/email",
  "/epics",
  "/forms",
  "/goals",
  "/hiring",
  "/inbox",
  "/insights",
  "/integrations",
  "/leaves",
  "/learning",
  "/onboarding",
  "/oncall",
  "/one-on-ones",
  "/people",
  "/predictions",
  "/projects",
  "/releases",
  "/reminders",
  "/reports",
  "/reviews",
  "/roadmap",
  "/settings",
  "/sprints",
  "/standups",
  "/stories",
  "/tables",
  "/teams",
  "/tracking",
  "/workflows",
  "/workspaces",
];

// Paths that are intentionally public even though they share a prefix above.
// `/onboarding/connect` is part of the OAuth flow where the user may arrive
// before the auth cookie is set; the page itself gates further actions on
// useAuth.
const AUTH_REQUIRED_EXCEPTIONS = ["/onboarding/connect"];

function isAuthRequiredPath(pathname: string): boolean {
  if (AUTH_REQUIRED_EXCEPTIONS.some((p) => pathname.startsWith(p))) return false;
  return AUTH_REQUIRED_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(p + "/") || (p.endsWith("/") && pathname.startsWith(p)),
  );
}

export function middleware(request: NextRequest) {
  // Read locale from cookie
  const cookieLocale = request.cookies.get("NEXT_LOCALE")?.value;
  const locale =
    cookieLocale && SUPPORTED_LOCALES.includes(cookieLocale)
      ? cookieLocale
      : DEFAULT_LOCALE;

  const { pathname } = request.nextUrl;

  // Logged-in visitors landing on "/" are sent straight to the app. This runs
  // at the edge on the aexy_authed presence cookie, so the marketing homepage
  // can render its full (crawlable) content unconditionally for everyone else
  // without a client-side redirect flash or gating spinner.
  if (pathname === "/" && request.cookies.get("aexy_authed")?.value) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }

  // Auth gate: redirect unauthenticated requests to the landing page before
  // any auth-required shell HTML is rendered. The cookie is a *presence*
  // signal mirrored from localStorage by useAuth — the JWT itself remains
  // in localStorage and is still validated by the API. Without this gate
  // the SSR-rendered app shell briefly leaks workspace placeholders and
  // React Query cache fragments before the client-side redirect fires.
  if (isAuthRequiredPath(pathname) && !request.cookies.get("aexy_authed")?.value) {
    const url = request.nextUrl.clone();
    // The whole address, not just the path. `/sprints?tab=epics` and `/sprints`
    // are different screens — Epics and Projects — so returning somebody to the
    // path alone silently lands them somewhere they did not ask for, and reads
    // as the tab they clicked having done nothing. The same is true of every
    // filtered list in the app, all of which keep their state in the query.
    const next = pathname + request.nextUrl.search;
    // Clearing first matters: `clone()` carries the original query, so without
    // this the params of the page they were denied leak onto the landing page
    // alongside `next` — which is how `/sprints?tab=epics` arrived here as
    // `/?tab=epics&next=%2Fsprints`.
    url.search = "";
    url.pathname = "/";
    url.searchParams.set("next", next);
    return NextResponse.redirect(url);
  }

  // Set locale header for i18n/request.ts to read
  const response = NextResponse.next();
  response.headers.set("x-locale", locale);

  return response;
}

export const config = {
  // Match all routes except static files, api routes, and Next.js internals
  matcher: ["/((?!_next|api|favicon.ico|.*\\..*).*)"],
};
