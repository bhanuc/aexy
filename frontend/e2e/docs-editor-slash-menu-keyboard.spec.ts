/**
 * E2E: the `/` block menu is fully keyboard-drivable.
 *
 * Reported: "When the menu list is shown I am not able to navigate with just
 * the arrow keys, have to use [the mouse] to select."
 *
 * Root cause: the menu is rendered with vanilla DOM and inline styles, and
 * every colour was written as a bare `var(--token)`. The theme tokens in
 * `globals.css` are HSL *component triplets* (`--accent: 75 14% 89%`) meant to
 * be consumed as `hsl(var(--accent))`, so `background: var(--accent)` was a
 * guaranteed-invalid value and painted nothing. Arrow keys were moving the
 * selection the whole time — there was simply never a highlight to see it by,
 * and the popup itself had no background either, so document text showed
 * through the menu.
 *
 * These assertions therefore cover both halves: that the selection *moves*
 * (observable state, not pixels) and that the menu is actually *opaque* so a
 * person can see it move.
 *
 * Live backend, no LLM.
 */

import { expect, test, type Page } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
  backendOnlyReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

const MENU = "[data-slash-menu]";
const ITEM = `${MENU} [role="option"]`;

/** Index of the currently highlighted row, or -1. */
async function selectedIndex(page: Page): Promise<number> {
  return page.evaluate(() => {
    const btns = Array.from(
      document.querySelectorAll('[data-slash-menu] [role="option"]'),
    );
    return btns.findIndex(
      (b) => (b as HTMLElement).dataset.selected === "true",
    );
  });
}

/** Opens the menu from an empty trailing paragraph. */
async function openSlashMenu(page: Page) {
  const editor = page.locator(".ProseMirror");
  await expect(editor).toBeVisible({ timeout: 20_000 });
  await editor.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.press("Enter");
  await page.keyboard.type("/");
  await expect(page.locator(MENU)).toBeVisible({ timeout: 10_000 });
}

test.describe("Docs editor / slash menu keyboard navigation (live)", () => {
  let docId: string | null = null;

  test.beforeEach(async ({ page, request }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
    const resp = await request.post(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents`,
      {
        headers: authHeaders(),
        data: {
          title: `e2e-slash-${Date.now()}`,
          visibility: "workspace",
          content: {
            type: "doc",
            content: [
              { type: "paragraph", content: [{ type: "text", text: "Intro" }] },
            ],
          },
        },
      },
    );
    expect(resp.ok(), `document create failed: ${resp.status()}`).toBe(true);
    docId = (await resp.json()).id;
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/docs/${docId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
  });

  test.afterEach(async ({ request }) => {
    if (docId) {
      await request
        .delete(
          `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents/${docId}`,
          { headers: authHeaders() },
        )
        .catch(() => {});
      docId = null;
    }
  });

  test("the menu opens with the first item highlighted", async ({ page }) => {
    await openSlashMenu(page);
    expect(await page.locator(ITEM).count()).toBeGreaterThan(3);
    expect(await selectedIndex(page)).toBe(0);
  });

  test("ArrowDown / ArrowUp move the highlight, and it wraps", async ({
    page,
  }) => {
    await openSlashMenu(page);
    const total = await page.locator(ITEM).count();

    await page.keyboard.press("ArrowDown");
    expect(
      await selectedIndex(page),
      "ArrowDown did not advance the highlight",
    ).toBe(1);

    await page.keyboard.press("ArrowDown");
    expect(await selectedIndex(page)).toBe(2);

    await page.keyboard.press("ArrowUp");
    expect(
      await selectedIndex(page),
      "ArrowUp did not move the highlight back",
    ).toBe(1);

    // Wrap backwards past the top onto the last row.
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("ArrowUp");
    expect(
      await selectedIndex(page),
      "highlight did not wrap from the first row to the last",
    ).toBe(total - 1);

    // And forwards past the bottom back onto the first.
    await page.keyboard.press("ArrowDown");
    expect(await selectedIndex(page)).toBe(0);
  });

  test("the highlight is actually visible — an opaque menu and a filled row", async ({
    page,
  }) => {
    await openSlashMenu(page);

    // The popup must paint its own background: with `var(--popover)` unwrapped
    // the menu was transparent and the document showed through it.
    const menuBg = await page
      .locator(MENU)
      .evaluate((el) => getComputedStyle(el as HTMLElement).backgroundColor);
    expect(
      menuBg,
      `slash menu background is "${menuBg}" — the popup is transparent`,
    ).not.toMatch(/rgba\(0,\s*0,\s*0,\s*0\)|transparent/);

    // And the selected row must differ from an unselected one.
    const rows = page.locator(ITEM);
    const bgOf = (i: number) =>
      rows
        .nth(i)
        .evaluate((el) => getComputedStyle(el as HTMLElement).backgroundColor);

    const selectedBg = await bgOf(0);
    const plainBg = await bgOf(1);
    expect(
      selectedBg,
      `highlighted row background is "${selectedBg}" — nothing is painted, so ` +
        `arrow-key movement is invisible`,
    ).not.toMatch(/rgba\(0,\s*0,\s*0,\s*0\)|transparent/);
    expect(
      selectedBg,
      "highlighted and unhighlighted rows look identical",
    ).not.toBe(plainBg);
  });

  test("Enter inserts the highlighted block, not the first one", async ({
    page,
  }) => {
    await openSlashMenu(page);

    // Filter to the headings so the target is unambiguous, then step to
    // Heading 3 and accept it with the keyboard alone.
    await page.keyboard.type("heading");
    await expect(page.locator(`${MENU} [data-slash-item="heading3"]`)).toBeVisible();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    expect(await selectedIndex(page)).toBe(2);
    await page.keyboard.press("Enter");

    await expect(page.locator(MENU)).toBeHidden({ timeout: 5_000 });
    await page.keyboard.type("Keyboard picked this");

    // Heading 3 — the third row — and not Heading 1, the default.
    await expect(
      page.locator(".ProseMirror h3", { hasText: "Keyboard picked this" }),
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page.locator(".ProseMirror h1", { hasText: "Keyboard picked this" }),
    ).toHaveCount(0);
  });

  test("Tab also accepts the highlighted item", async ({ page }) => {
    await openSlashMenu(page);
    await page.keyboard.type("bullet");
    await expect(page.locator(`${MENU} [data-slash-item="bullet_list"]`)).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.locator(MENU)).toBeHidden({ timeout: 5_000 });
    await page.keyboard.type("Tabbed item");
    await expect(
      page.locator(".ProseMirror ul li", { hasText: "Tabbed item" }),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("Escape dismisses the menu and leaves the typing alone", async ({
    page,
  }) => {
    await openSlashMenu(page);
    await page.keyboard.press("Escape");
    await expect(page.locator(MENU)).toBeHidden({ timeout: 5_000 });
  });

  test("arrow keys are not swallowed when nothing matches", async ({ page }) => {
    await openSlashMenu(page);
    await page.keyboard.type("zzzznotacommand");
    await expect(page.locator("[data-slash-menu-empty]")).toBeVisible();

    // With no items the menu must hand the keystroke back to the editor
    // rather than consuming it (and must not leave selectedIndex as NaN).
    await page.keyboard.press("ArrowDown");
    expect(await selectedIndex(page)).toBe(-1);
    await page.keyboard.press("ArrowUp");
    expect(await selectedIndex(page)).toBe(-1);
  });
});
