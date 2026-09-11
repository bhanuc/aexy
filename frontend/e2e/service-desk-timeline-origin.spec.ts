/**
 * E2E: the handoff timeline says how the ticket arrived and who from.
 *
 * The timeline's first entry read "Ticket created" and nothing more — the one
 * entry that should answer "where did this come from" was the one entry that
 * didn't. Both facts were already on the ticket and already rendered further up
 * the same page: `origin` as a Source field, and the requester beside the
 * conversation. The timeline just never used them.
 *
 * `SegmentResponse.changed_by_id` was likewise carried and ignored, so a later
 * handoff could not say who moved it either.
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

async function logManualTicket(request: APIRequestContext, subject: string) {
  const resp = await request.post(
    `${API_BASE}/workspaces/${WS()}/service-desk/tickets/manual`,
    {
      headers: authHeaders(),
      data: {
        subject,
        body: "Raised by the timeline origin spec.",
        requester_email: "caller@example.com",
        requester_name: "A Caller",
      },
    },
  );
  expect(resp.ok(), `manual ticket create failed: ${resp.status()}`).toBe(true);
  return (await resp.json()).ticket_id as string;
}

test.describe("Service Desk timeline origin (live)", () => {
  let ticketId: string | null = null;

  test.beforeEach(async ({ page, request }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
    ticketId = await logManualTicket(request, `e2e-origin-${Date.now()}`);
    await page.setViewportSize({ width: 1600, height: 1000 });
  });

  test("the arrival entry names the channel and who logged it", async ({
    page,
  }) => {
    await page.goto(`/service-desk/tickets/${ticketId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    const timeline = page.getByTestId("sd-timeline");
    await expect(timeline).toBeVisible({ timeout: 60_000 });

    const text = await timeline.innerText();

    // A manual ticket is logged by somebody here, so both halves are knowable:
    // the channel it came in on, and the person who took it down.
    expect(
      text,
      `the timeline does not say how the ticket arrived:\n${text}`,
    ).toContain("Phone or WhatsApp");
    expect(
      text,
      `the timeline does not say who logged the ticket:\n${text}`,
    ).toMatch(/logged by \S+/i);

    // The regression this guards: an arrival entry carrying only the bare
    // "Ticket created" note, with no channel and no person.
    const arrival = text.split("\n").findIndex((l) => /Ticket created/i.test(l));
    expect(arrival, "no creation entry in the timeline").toBeGreaterThan(-1);
    expect(
      text.split("\n").slice(0, arrival).join(" "),
      "the creation entry is not preceded by how it arrived",
    ).toMatch(/Phone or WhatsApp|Email|Internal email/);
  });

  test("the Source field and the timeline agree on the channel", async ({
    page,
  }) => {
    await page.goto(`/service-desk/tickets/${ticketId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    await expect(page.getByTestId("sd-timeline")).toBeVisible({
      timeout: 60_000,
    });

    // Two places on one page describing the same fact; they must not drift.
    const body = await page.locator("main").innerText();
    const channel = "Phone or WhatsApp";
    const occurrences = body.split(channel).length - 1;
    expect(
      occurrences,
      `expected the channel in both the Source field and the timeline, saw ${occurrences}`,
    ).toBeGreaterThanOrEqual(2);
  });

  // No cleanup: the desk has no ticket-delete endpoint, by design — a ticket is
  // a record of something that happened and is closed rather than removed. Each
  // run therefore leaves one logged ticket behind, which is why the subjects are
  // stamped with a timestamp and say where they came from.
});
