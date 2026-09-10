/**
 * E2E: SearchModal exposes the right ARIA contract.
 *
 * Audit finding (Cluster 3, item a): the docs surface has zero
 * role/aria-modal/aria-label declarations across 6,585 LOC. The
 * SearchModal mounted via Cmd+K is the most-used overlay — needs
 * role="dialog", aria-modal, and an accessible label so screen-reader
 * users can identify it.
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

test.describe("Docs SearchModal a11y (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("SearchModal has role=dialog + aria-modal + aria-label", async ({
    page,
  }) => {
    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });

    // The Cmd+K listener lives in a `useEffect` in DocsLayoutClient, so it
    // only exists once React has hydrated. A single press after a fixed 1s
    // wait was landing before that on the dev server (a first paint here
    // measures ~2s) and the keystroke went nowhere, with nothing to retry it.
    // Wait for the page to be interactive, then press until the modal answers.
    const search = page.getByPlaceholder(/search documents/i);
    await expect(page.getByRole("main")).toBeVisible({ timeout: 60_000 });
    await expect(async () => {
      await page.keyboard.press(
        process.platform === "darwin" ? "Meta+K" : "Control+K",
      );
      // Proves the capture-phase interception beat the global palette.
      await expect(search).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 30_000 });

    // The modal root must be a dialog with aria-modal=true and a
    // non-empty accessible label.
    const dialog = page.getByRole("dialog").filter({ has: page.getByPlaceholder(/search documents/i) }).first();
    await expect(
      dialog,
      "SearchModal isn't marked role='dialog' — assistive tech can't identify it as an overlay",
    ).toBeVisible({ timeout: 3_000 });

    const ariaModal = await dialog.getAttribute("aria-modal");
    expect(ariaModal, "aria-modal missing on SearchModal").toBe("true");

    const label =
      (await dialog.getAttribute("aria-label")) ??
      (await dialog.getAttribute("aria-labelledby"));
    expect(
      label,
      "SearchModal has no aria-label or aria-labelledby — add a descriptive label",
    ).toBeTruthy();
  });
});
