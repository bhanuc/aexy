/**
 * E2E: the ticket page has one scroll, not two.
 *
 * Reported: "once you scroll past the ticket details you are able to scroll
 * more" — reaching the bottom of the ticket column and carrying on dragged the
 * whole application up, leaving empty page beneath the sidebar and the content.
 *
 * The app shell is `h-screen overflow-hidden` precisely so the document never
 * scrolls; only the content column does. What broke that was the file input
 * behind "attach a file": Tailwind's `sr-only` positions it absolutely, and an
 * absolutely-positioned element is clipped by an ancestor's `overflow` only if
 * that ancestor is itself positioned. Its containing block was therefore the
 * page, so it was laid out at the document coordinate of its static position —
 * below the fold on a long ticket — and stretched the document past the
 * viewport. The wheel then chained from the column to the window.
 *
 * Checked by behaviour rather than by CSS: scroll the column to its end, keep
 * wheeling, and the window must not move.
 *
 * Live backend, no LLM.
 */

import { expect, test, type APIRequestContext } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
  backendOnlyReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

const WS = () => REAL_BACKEND_WORKSPACE_ID;

async function logTicket(request: APIRequestContext) {
  const resp = await request.post(
    `${API_BASE}/workspaces/${WS()}/service-desk/tickets/manual`,
    {
      headers: authHeaders(),
      data: {
        subject: `e2e-scroll-${Date.now()}`,
        // Long enough that the column genuinely overflows, which is the only
        // state in which chaining can happen at all.
        body: Array.from({ length: 60 }, (_, i) => `Line ${i} of the scroll fixture.`).join("\n"),
        requester_email: "scroll@example.com",
        requester_name: "Scroll Fixture",
      },
    },
  );
  expect(resp.ok(), `manual ticket create failed: ${resp.status()}`).toBe(true);
  return (await resp.json()).ticket_id as string;
}

test.describe("Service Desk ticket page scrolling (live)", () => {
  let ticketId: string | null = null;

  test.beforeEach(async ({ page, request }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
    ticketId = await logTicket(request);
    // A short viewport so the ticket column certainly overflows.
    await page.setViewportSize({ width: 1440, height: 800 });
  });

  test("the window does not scroll once the ticket column runs out", async ({
    page,
  }) => {
    await page.goto(`/service-desk/tickets/${ticketId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    await expect(page.getByTestId("sd-timeline")).toBeVisible({ timeout: 60_000 });
    await page.waitForTimeout(1_500);

    const docFits = () =>
      page.evaluate(
        () => document.documentElement.scrollHeight <= window.innerHeight + 1,
      );
    expect(
      await docFits(),
      "the document is taller than the viewport, so the shell can be scrolled " +
        "away from under the app",
    ).toBe(true);

    // Drive the column to its end, then keep going — the reported gesture.
    await page.evaluate(() => {
      const column = [...document.querySelectorAll<HTMLElement>("*")].find(
        (el) =>
          /overflow-y-auto/.test(el.className?.toString?.() ?? "") &&
          el.scrollHeight > el.clientHeight + 2 &&
          el.clientHeight > 300,
      );
      if (column) column.scrollTop = column.scrollHeight;
    });
    await page.mouse.move(720, 400);
    for (let i = 0; i < 10; i++) {
      await page.mouse.wheel(0, 400);
      await page.waitForTimeout(80);
    }

    expect(
      await page.evaluate(() => window.scrollY),
      "the wheel chained from the ticket column to the window — scrolling past " +
        "the ticket drags the whole shell up",
    ).toBe(0);
    expect(await docFits(), "the document grew while scrolling").toBe(true);
  });

  // No cleanup: the desk has no ticket-delete endpoint, by design — a ticket is
  // a record of something that happened and is closed rather than removed.
});
