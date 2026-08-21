/**
 * One-off capture tool for the homepage product tour — NOT part of the test
 * suite (playwright.config.ts only picks up e2e/*.spec.ts).
 *
 * Captures real app surfaces as the dark "plates" the Open Ledger homepage
 * frames. Wire the results into SHOTS in
 * src/components/landing/home/ProductTour.tsx via static imports.
 *
 * Prereqs:
 *   docker-compose up -d          (backend :8000, frontend :3000)
 *   docker exec aexy-backend python scripts/generate_test_token.py --first
 *
 * Run:
 *   AEXY_TEST_TOKEN=<jwt> npx tsx e2e/tools/capture-marketing-shots.ts
 *
 * Output: public/marketing/home/home-<surface>@2x.png — convert to WebP with
 *   npx sharp-cli --input "public/marketing/home/*.png" --format webp -q 75
 * Filenames must stay query-string free: Next 16 400s local images with
 * search params unless allowlisted (images.localPatterns[].search).
 */

import { chromium } from "@playwright/test";
import { mkdirSync } from "fs";
import { join } from "path";

const BASE = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";
const TOKEN = process.env.AEXY_TEST_TOKEN;
const OUT = join(__dirname, "..", "..", "public", "marketing", "home");

// Surface → route. Adjust routes to whatever has presentable seeded data;
// screenshots must look real without exposing anything private.
// "build" is filled in at runtime — the sprint board lives under the seeded
// project's id, resolved from the API rather than hardcoded.
// readyText is a string the seeded data must render before the shot is taken:
// pages hydrate through fetch chains (sprints → active sprint → tasks), and
// "skeletons gone" alone still photographs the empty state on a cold cache.
const SHOTS: Array<{ name: string; path: string; readySelector: string; readyText: string }> = [
  { name: "sell", path: "/crm/deal", readySelector: "main", readyText: "Northwind" },
  { name: "build", path: "", readySelector: "main", readyText: "Rate-limit the webhook retry" },
  { name: "operate", path: "/automations", readySelector: "main", readyText: "Uptime alert" },
  { name: "grow", path: "/reviews", readySelector: "main", readyText: "Q3 Engineering Reviews" },
  { name: "know", path: "/docs", readySelector: "main", readyText: "Incident runbook" },
];

async function main() {
  if (!TOKEN) {
    console.error("AEXY_TEST_TOKEN is required — see the header comment.");
    process.exit(1);
  }
  mkdirSync(OUT, { recursive: true });

  // The CRM Google-connect banner persists its dismissal per workspace, so
  // resolve the workspace id first to pre-dismiss it below.
  const wsResponse = await fetch("http://localhost:8000/api/v1/workspaces", {
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  const workspaces = (await wsResponse.json()) as Array<{ id: string }>;
  const workspaceId = workspaces[0]?.id ?? "";

  const projectsResponse = await fetch(
    `http://localhost:8000/api/v1/workspaces/${workspaceId}/projects`,
    { headers: { Authorization: `Bearer ${TOKEN}` } },
  );
  const projectsPayload = (await projectsResponse.json()) as
    | Array<{ id: string }>
    | { projects?: Array<{ id: string }>; items?: Array<{ id: string }> };
  const projects = Array.isArray(projectsPayload)
    ? projectsPayload
    : projectsPayload.projects ?? projectsPayload.items ?? [];
  if (!projects[0]?.id) {
    console.error("no project found — run scripts/seed_marketing_demo.py first");
    process.exit(1);
  }
  const buildShot = SHOTS.find((s) => s.name === "build")!;
  buildShot.path = `/sprints/${projects[0].id}/board`;

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor: 2,
  });
  // Presence cookie first so the middleware lets the shell render, then the
  // real token before any app code runs.
  await context.addCookies([
    { name: "aexy_authed", value: "1", url: BASE },
  ]);
  await context.addInitScript(
    ({ token, wsId }: { token: string; wsId: string }) => {
      window.localStorage.setItem("token", token);
      // Marketing shots are taken in light mode (zustand-persisted preference,
      // applied by the theme provider before first paint).
      window.localStorage.setItem(
        "aexy-theme",
        JSON.stringify({ state: { theme: "light" }, version: 0 }),
      );
      // Pre-dismiss the free-tier upgrade nudge and the CRM Google banner the
      // way a user would — via their own persistence keys — so a fresh capture
      // context doesn't resurrect them into the frame.
      for (const trigger of ["module_limit", "automation_limit", "generic"]) {
        window.localStorage.setItem(`upgrade_banner_dismissed_${trigger}`, "true");
      }
      if (wsId) {
        window.localStorage.setItem(`crm_google_banner_dismissed_${wsId}`, "true");
      }
    },
    { token: TOKEN, wsId: workspaceId },
  );

  const page = await context.newPage();
  for (const shot of SHOTS) {
    await page.goto(`${BASE}${shot.path}`, { waitUntil: "networkidle" });
    await page.waitForSelector(shot.readySelector, { timeout: 30_000 });
    // Capture hygiene: no toasts, no floating chat bubble, no nprogress, no
    // Next dev-tools badge — transient chrome that reads as clutter in a
    // marketing frame.
    await page.addStyleTag({
      content:
        "[data-sonner-toaster], #nprogress, .fixed.bottom-6.right-6, nextjs-portal { display: none !important; }",
    });
    // Spinners and skeleton shimmer photograph as a broken page — wait for
    // both to clear (best-effort: a decorative pulse dot shouldn't hang the
    // whole run, hence the catch).
    await page
      .waitForFunction(
        () =>
          document.querySelectorAll(".animate-spin").length === 0 &&
          document.querySelectorAll(".animate-pulse").length === 0,
        undefined,
        { timeout: 20_000 },
      )
      .catch(() => console.warn(`spinner/skeleton still visible on ${shot.path}`));
    await page
      .getByText(shot.readyText)
      .first()
      .waitFor({ timeout: 30_000 })
      .catch(() => console.warn(`seeded content "${shot.readyText}" never appeared on ${shot.path}`));
    await page.waitForTimeout(1_500); // let charts and images settle
    const file = join(OUT, `home-${shot.name}@2x.png`);
    await page.screenshot({ path: file });
    console.log(`captured ${file}`);
  }

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
