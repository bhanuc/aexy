/**
 * E2E: formatting a selection, and the reason there is no floating menu.
 *
 * This file used to assert a `@tiptap/react` BubbleMenu — a floating B/I bar
 * near the selection — from an audit finding that the non-collaborative editor
 * path had no such bar. One was added and then deliberately removed:
 * `BubbleMenu` wraps Tippy.js, which appends its DOM into `document.body`,
 * outside the React tree. Every `selectionchange` moves those nodes, and
 * React's reconciler then tries to remove a node from a parent that no longer
 * owns it and throws
 *
 *     removeChild: The node to be removed is not a child of this node
 *
 * in the commit phase, taking the whole editor down. The note at
 * `DocumentEditor.tsx:619` records that and the replacement: the toolbar is
 * sticky (`DocumentEditor.tsx:490`), so Bold / Italic / Underline / Code stay
 * on screen at any scroll position and need no floating positioning to reach.
 *
 * So the old expectation described an implementation that was reverted on
 * purpose, and the test could only ever be red. What matters is checked here
 * instead:
 *
 *   1. a selection can actually be formatted, which is what the audit wanted;
 *   2. the toolbar really is reachable at any scroll depth, which is what
 *      makes a floating menu unnecessary rather than merely absent;
 *   3. rapid selection changes raise no reconciler error — the failure that
 *      caused the removal, and the thing that breaks if anyone reintroduces a
 *      body-portaled menu.
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

/**
 * Select a whole paragraph from the keyboard. Triple-click works on plain
 * text but leaves the selection collapsed once the paragraph's content is
 * wrapped in a mark element (`<strong>…</strong>`), so it cannot be used to
 * apply a second mark on top of a first.
 */
async function selectParagraph(page: Page, index: number) {
  const para = page.locator(".ProseMirror p").nth(index);
  await para.click();
  await page.keyboard.press("Home");
  await page.keyboard.press("Shift+End");
  await expect
    .poll(
      () => page.evaluate(() => (window.getSelection()?.toString() ?? "").length),
      { message: `paragraph ${index} did not end up selected` },
    )
    .toBeGreaterThan(0);
}

/** Enough paragraphs that the toolbar's stickiness is actually tested. */
const LONG_DOC = {
  type: "doc",
  content: Array.from({ length: 60 }, (_, i) => ({
    type: "paragraph",
    content: [{ type: "text", text: `Paragraph ${i} of the selection test.` }],
  })),
};

test.describe("Docs editor selection formatting (live)", () => {
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
          title: `e2e-selection-${Date.now()}`,
          visibility: "workspace",
          content: LONG_DOC,
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
    await expect(page.locator(".ProseMirror").first()).toBeVisible({
      timeout: 20_000,
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

  test("a selection can be bolded and italicised from the toolbar", async ({
    page,
  }) => {
    await selectParagraph(page, 0);
    await page.getByLabel("Bold", { exact: true }).click();
    await expect(
      page.locator(".ProseMirror strong", { hasText: "Paragraph 0" }),
      "the selection did not become bold",
    ).toBeVisible({ timeout: 10_000 });

    // Re-select — clicking the toolbar moved focus — then italicise on top,
    // which is where a collapsed selection would silently do nothing.
    await selectParagraph(page, 0);
    await page.getByLabel("Italic", { exact: true }).click();
    await expect(
      page.locator(".ProseMirror em"),
      "the selection did not become italic",
    ).toBeVisible({ timeout: 10_000 });

    // Both marks on the same run, so neither click replaced the other.
    await expect(
      page.locator(".ProseMirror strong em, .ProseMirror em strong"),
      "bold and italic did not both survive on the same text",
    ).toHaveCount(1, { timeout: 10_000 });
  });

  test("the toolbar stays on screen deep into a long document", async ({
    page,
  }) => {
    const bold = page.getByLabel("Bold", { exact: true });
    await expect(bold).toBeVisible();

    // Scroll to the end of a 60-paragraph document.
    await page.locator(".ProseMirror").click();
    await page.keyboard.press("Control+End");
    await page.mouse.wheel(0, 4000);
    await page.waitForTimeout(500);

    await expect(
      bold,
      "the toolbar scrolled away — without it in reach, a floating selection " +
        "menu would be the only way to format text",
    ).toBeInViewport({ timeout: 10_000 });

    const count = await page.locator(".ProseMirror p").count();
    await selectParagraph(page, count - 1);
    await bold.click();
    await expect(page.locator(".ProseMirror strong").last()).toBeVisible({
      timeout: 10_000,
    });
  });

  test("no floating menu is portaled to the body, and selection churn is clean", async ({
    page,
  }) => {
    const fatal: string[] = [];
    page.on("pageerror", (err) => fatal.push(String(err)));
    page.on("console", (msg) => {
      if (msg.type() === "error") fatal.push(msg.text());
    });

    // Churn the selection the way a person skimming a document does. This is
    // the exact pattern that made the Tippy-based BubbleMenu mount and unmount
    // per selectionchange and throw from the commit phase.
    for (let i = 0; i < 12; i++) {
      await selectParagraph(page, i);
      await page.waitForTimeout(80);
    }
    await page.locator(".ProseMirror").click();
    await page.keyboard.press("Control+End");
    await page.waitForTimeout(300);

    // Nothing Tippy-shaped should be sitting directly under <body>.
    const portaled = await page.evaluate(() =>
      Array.from(document.body.children).filter((el) =>
        el.className?.toString?.().includes("tippy-box"),
      ).length,
    );
    expect(
      portaled,
      "a Tippy popup is portaled under <body> for the selection — that is the " +
        "shape that crashed the reconciler",
    ).toBe(0);

    const reconciler = fatal.filter((m) =>
      /removeChild|not a child of this node|NotFoundError/i.test(m),
    );
    expect(
      reconciler,
      `reconciler errors during selection churn:\n  ${reconciler.join("\n  ")}`,
    ).toEqual([]);
  });
});
