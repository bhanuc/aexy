/**
 * E2E: every block the `/` menu can insert survives a save and a reload.
 *
 * The editor autosaves TipTap JSON and re-hydrates from it on the next visit,
 * so a block that the schema can create but not parse back is silently lost —
 * the kind of thing you only notice by returning to a document later. This
 * walks the whole `/` catalogue and checks each block is still there after a
 * round-trip through the backend.
 *
 * Split into one test per block so a single unparseable block names itself
 * instead of failing an opaque "some block went missing".
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

test.describe.configure({ timeout: 150_000 });

const MENU = "[data-slash-menu]";
/** Autosave is debounced; give it room to fire and land. */
const SAVE_SETTLE_MS = 3_500;

/** Inserts a block through the `/` menu, keyboard only, then types text. */
async function insertBlock(page: Page, commandId: string, text?: string) {
  const editor = page.locator(".ProseMirror");
  await editor.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.press("Enter");
  await page.keyboard.type("/");
  await expect(page.locator(MENU)).toBeVisible({ timeout: 10_000 });
  await page.keyboard.type(commandId.replace(/_/g, " ").split(" ")[0]);
  const item = page.locator(`${MENU} [data-slash-item="${commandId}"]`);
  await expect(
    item,
    `"${commandId}" is not reachable by typing in the / menu`,
  ).toBeVisible({ timeout: 10_000 });
  // Step the highlight onto the wanted row, then accept with Enter.
  const idx = await item.evaluate((el) => Number((el as HTMLElement).dataset.index));
  for (let i = 0; i < idx; i++) await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.locator(MENU)).toBeHidden({ timeout: 10_000 });
  if (text) await page.keyboard.type(text);
}

const BLOCKS: {
  id: string;
  text?: string;
  /** Selector that must hold after the reload. */
  expect: string;
  /** Nothing to type into it (atoms, rules). */
  atom?: boolean;
}[] = [
  { id: "heading1", text: "RT Heading One", expect: ".ProseMirror h1" },
  { id: "heading2", text: "RT Heading Two", expect: ".ProseMirror h2" },
  { id: "heading3", text: "RT Heading Three", expect: ".ProseMirror h3" },
  { id: "bullet_list", text: "RT bullet", expect: ".ProseMirror ul li" },
  { id: "numbered_list", text: "RT numbered", expect: ".ProseMirror ol li" },
  {
    id: "task_list",
    text: "RT task",
    expect: '.ProseMirror ul[data-type="taskList"] li',
  },
  { id: "blockquote", text: "RT quote", expect: ".ProseMirror blockquote" },
  { id: "code_block", text: "RT code", expect: ".ProseMirror pre" },
  { id: "divider", expect: ".ProseMirror hr", atom: true },
  { id: "table", expect: ".ProseMirror table", atom: true },
];

test.describe("Docs editor / slash-menu blocks survive a reload (live)", () => {
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
          title: `e2e-roundtrip-${Date.now()}`,
          visibility: "workspace",
          content: {
            type: "doc",
            content: [
              { type: "paragraph", content: [{ type: "text", text: "Start" }] },
            ],
          },
        },
      },
    );
    expect(resp.ok(), `document create failed: ${resp.status()}`).toBe(true);
    docId = (await resp.json()).id;
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto(`/docs/${docId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    await expect(page.locator(".ProseMirror")).toBeVisible({ timeout: 20_000 });
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

  for (const block of BLOCKS) {
    test(`${block.id} round-trips`, async ({ page, request }) => {
      await insertBlock(page, block.id, block.text);

      const inserted = block.text
        ? page.locator(block.expect, { hasText: block.text })
        : page.locator(block.expect);
      await expect(inserted, `${block.id} did not render on insert`).toBeVisible({
        timeout: 10_000,
      });

      await page.waitForTimeout(SAVE_SETTLE_MS);

      // The backend must be holding it, not just the browser.
      const saved = await request.get(
        `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents/${docId}`,
        { headers: authHeaders() },
      );
      expect(saved.ok()).toBe(true);
      const savedJson = JSON.stringify((await saved.json()).content ?? {});
      if (block.text) {
        expect(
          savedJson,
          `${block.id}: the typed text never reached the backend`,
        ).toContain(block.text);
      }

      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.locator(".ProseMirror")).toBeVisible({ timeout: 20_000 });
      await expect(
        block.text
          ? page.locator(block.expect, { hasText: block.text })
          : page.locator(block.expect),
        `${block.id} was lost across the save/reload round-trip`,
      ).toBeVisible({ timeout: 15_000 });
    });
  }

  test("an inline database round-trips with its table link intact", async ({
    page,
    request,
  }) => {
    const tableResp = await request.post(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/tables`,
      {
        headers: authHeaders(),
        data: { name: `e2e-rt-${Date.now()}`, visibility: "workspace" },
      },
    );
    test.skip(
      !tableResp.ok(),
      `tables API unavailable (${tableResp.status()})`,
    );
    const table = await tableResp.json();

    await request.patch(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents/${docId}`,
      {
        headers: authHeaders(),
        data: {
          content: {
            type: "doc",
            content: [
              { type: "paragraph", content: [{ type: "text", text: "Start" }] },
              {
                type: "inlineDatabase",
                attrs: {
                  tableId: table.id,
                  scope: "standalone",
                  height: 400,
                  collapsed: false,
                },
              },
            ],
          },
        },
      },
    );

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("inline-database-node")).toBeVisible({
      timeout: 25_000,
    });

    // Collapse it — an attribute write — and confirm the attribute persists,
    // which is what proves the node's attrs survive the round-trip and not
    // just its type.
    await page.getByLabel("Collapse database").click();
    await page.waitForTimeout(SAVE_SETTLE_MS);

    const after = await request.get(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents/${docId}`,
      { headers: authHeaders() },
    );
    const content = JSON.stringify((await after.json()).content ?? {});
    expect(content, "the embed lost its table link on save").toContain(table.id);
    expect(content, "the collapsed state was not saved").toContain(
      '"collapsed":true',
    );

    await request
      .delete(
        `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/tables/${table.id}`,
        { headers: authHeaders() },
      )
      .catch(() => {});
  });
});
