/**
 * E2E environment flags.
 *
 * Two run modes:
 *
 * 1. **Mock mode** (default) — `page.route(...)` intercepts every backend
 *    call, fulfilled with stubbed responses. Fast, deterministic, no
 *    network or auth needed. This is what most specs assume.
 *
 * 2. **Live mode** — `E2E_REAL_BACKEND=1`. No mocks installed; the
 *    frontend talks to a real backend at `NEXT_PUBLIC_API_URL`. The
 *    test runner needs a real JWT (`AEXY_TEST_TOKEN`) and the workspace
 *    UUID to drive (`AEXY_TEST_WORKSPACE_ID`). Specs that depend on
 *    spied `makeSpiedRoute` payload assertions are skipped — only the
 *    "does the page load + the user action complete" portion runs.
 *
 *    Generate a token: `docker exec aexy-backend python scripts/generate_test_token.py --first`
 *
 *    Run: `E2E_REAL_BACKEND=1 AEXY_TEST_TOKEN=<jwt> AEXY_TEST_WORKSPACE_ID=<uuid> \
 *           PLAYWRIGHT_BASE_URL=http://localhost:3000 \
 *           npx playwright test reviews-self-review.spec.ts`
 *
 * The flag is read once at import time; flip it via env vars, not at
 * runtime.
 */

import { APP_CATALOG } from "@/config/appDefinitions";

export const USE_REAL_BACKEND = process.env.E2E_REAL_BACKEND === "1";

/**
 * In live mode, the spec MUST set these or it'll fail with a 401 on
 * the first request. We surface a precise error rather than letting
 * the user puzzle over a confusing 401 trace.
 */
export const REAL_BACKEND_TOKEN = process.env.AEXY_TEST_TOKEN ?? "";
export const REAL_BACKEND_WORKSPACE_ID =
  process.env.AEXY_TEST_WORKSPACE_ID ?? "";

/**
 * Token is required for ANY live-mode test. Workspace ID is only
 * required for tests that navigate the UI (so the page-shell knows
 * which workspace to bootstrap into). Contract tests that POST
 * directly with the JWT need only the token.
 */
export function assertLiveModeReady(opts: { workspace?: boolean } = {}): void {
  if (!USE_REAL_BACKEND) return;
  const missing: string[] = [];
  if (!REAL_BACKEND_TOKEN) missing.push("AEXY_TEST_TOKEN");
  if (opts.workspace !== false && !REAL_BACKEND_WORKSPACE_ID) {
    missing.push("AEXY_TEST_WORKSPACE_ID");
  }
  if (missing.length > 0) {
    throw new Error(
      `E2E_REAL_BACKEND=1 but missing env vars: ${missing.join(", ")}. ` +
        `Generate a token with: ` +
        `docker exec aexy-backend python scripts/generate_test_token.py --first`,
    );
  }
}

/**
 * Prime a mock-mode page so the Next.js middleware lets it through.
 *
 * `src/middleware.ts` redirects every auth-required path to `/` unless the
 * `aexy_authed` presence cookie is set, and it does that at the edge — before
 * any page code runs. Mock-mode specs were priming `localStorage` in an init
 * script, which is client-side and therefore far too late: the navigation had
 * already been bounced, and the spec then searched a marketing landing page
 * for app UI and failed with a confusing "element not found".
 *
 * The live-mode counterpart is `setupAiLiveAuth` in `ai-env.ts`, which does
 * the same thing with a real JWT. Call this BEFORE the first `page.goto`.
 */
export async function setupMockAuth(
  page: import("@playwright/test").Page,
  opts: { workspaceId?: string; grantAllApps?: boolean } = {},
): Promise<void> {
  const workspaceId = opts.workspaceId ?? "ws-1";
  const baseUrl = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";

  await page.context().addCookies([
    { name: "aexy_authed", value: "1", url: baseUrl, sameSite: "Lax" },
  ]);

  await page.addInitScript(
    ([ws]) => {
      try {
        localStorage.setItem("token", "fake-test-token");
        localStorage.setItem("current_workspace_id", ws);
      } catch {
        // localStorage can be unavailable in some contexts — ignore.
      }
    },
    [workspaceId],
  );

  if (opts.grantAllApps !== false) {
    // Past the middleware there is a second gate: `useAppAccess` resolves the
    // viewer's per-app permissions, and `hasAppAccess` deliberately returns
    // false until that has loaded. A spec that mocks neither lands on "You
    // don't have access to this page" rather than the page it asked for.
    // Granting everything is right for a mock-mode spec, whose subject is the
    // page's behaviour and not the access resolver — the resolver has its own
    // tests (appCatalogParity, appAccessFailureUx).
    const apiBase =
      process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
    await page.route(
      `${apiBase}/workspaces/*/app-access/members/*/effective`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            // Built from the catalogue rather than hand-listed, so it cannot
            // drift as apps are added. (A Proxy would not survive
            // JSON.stringify — it enumerates own keys, of which there are
            // none.)
            apps: Object.fromEntries(
              Object.keys(APP_CATALOG).map((appId) => [
                appId,
                { app_id: appId, enabled: true, reachable: true },
              ]),
            ),
            applied_template_id: null,
            applied_template_name: null,
            has_custom_overrides: false,
            is_admin: true,
            baseline: "member_template",
            departments: [],
            suggested_persona: null,
          }),
        }),
    );
    await page.route(
      `${apiBase}/workspaces/*/app-access/requests/mine**`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "[]",
        }),
    );
  }
}
