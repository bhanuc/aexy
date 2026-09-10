/**
 * E2E: a table or an inline database can be taken back OUT of a document.
 *
 * Reported: "Unable to remove the added table and database."
 *
 * Both were one-way doors:
 *
 *  - **Table.** `EditorToolbar` offered "Insert Table" and nothing else, the
 *    BubbleMenu that would normally carry row/column controls was deliberately
 *    removed (see the note in `DocumentEditor.tsx`), and ProseMirror will not
 *    delete a table from a cell selection with Backspace. So an inserted table
 *    was permanent.
 *  - **Inline database.** The node view rendered a collapse button and an
 *    "open in module" link, but never called `deleteNode`. Its placeholder
 *    state was worse: every mode's Cancel/Back returned to "choose", and
 *    "choose" only offered the three ways forward.
 *
 * Removing an inline database is a *document* edit — it drops the embed and
 * leaves the underlying table and its rows alone, which is what the linked
 * CRM/project case requires. That distinction is asserted here too.
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
  backendOnlyReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

const MENU = "[data-slash-menu]";

test.describe("Docs editor / removing tables and databases (live)", () => {
  let docId: string | null = null;

  async function createDoc(request: Parameters<typeof authHeaders> extends never ? never : any) {
    const resp = await request.post(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents`,
      {
        headers: authHeaders(),
        data: {
          title: `e2e-remove-${Date.now()}`,
          visibility: "workspace",
          content: {
            type: "doc",
            content: [
              { type: "paragraph", content: [{ type: "text", text: "Body" }] },
            ],
          },
        },
      },
    );
    expect(resp.ok(), `document create failed: ${resp.status()}`).toBe(true);
    return (await resp.json()).id as string;
  }

  test.beforeEach(async ({ page, request }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
    docId = await createDoc(request);
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

  // ─── Tables ──────────────────────────────────────────────────────

  test("table controls appear only while the caret is inside a table", async ({
    page,
  }) => {
    const del = page.getByTestId("delete-table");
    await expect(
      del,
      "table controls should stay hidden with no table in play",
    ).toHaveCount(0);

    await page.locator(".ProseMirror").click();
    await page.keyboard.press("Control+End");
    await page.keyboard.press("Enter");
    await page.keyboard.type("/table");
    await expect(page.locator(`${MENU} [data-slash-item="table"]`)).toBeVisible({
      timeout: 10_000,
    });
    await page.keyboard.press("Enter");

    await expect(page.locator(".ProseMirror table")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      del,
      "the caret lands in the table, so its controls should be offered",
    ).toBeVisible({ timeout: 10_000 });
  });

  test("Delete table removes the table from the document", async ({ page }) => {
    await page.locator(".ProseMirror").click();
    await page.keyboard.press("Control+End");
    await page.keyboard.press("Enter");
    await page.keyboard.type("/table");
    await expect(page.locator(`${MENU} [data-slash-item="table"]`)).toBeVisible({
      timeout: 10_000,
    });
    await page.keyboard.press("Enter");
    await expect(page.locator(".ProseMirror table")).toBeVisible({
      timeout: 10_000,
    });

    await page.getByTestId("delete-table").click();

    await expect(
      page.locator(".ProseMirror table"),
      "the table survived Delete table",
    ).toHaveCount(0, { timeout: 10_000 });
  });

  test("row and column deletion shrink the table", async ({ page }) => {
    await page.locator(".ProseMirror").click();
    await page.keyboard.press("Control+End");
    await page.keyboard.press("Enter");
    await page.keyboard.type("/table");
    await expect(page.locator(`${MENU} [data-slash-item="table"]`)).toBeVisible({
      timeout: 10_000,
    });
    await page.keyboard.press("Enter");

    const table = page.locator(".ProseMirror table");
    await expect(table).toBeVisible({ timeout: 10_000 });
    const rows = page.locator(".ProseMirror table tr");
    const startRows = await rows.count();
    expect(startRows).toBeGreaterThan(1);

    await page.getByLabel("Delete row").click();
    await expect(rows).toHaveCount(startRows - 1, { timeout: 10_000 });

    const firstRowCells = page.locator(".ProseMirror table tr").first().locator("th, td");
    const startCols = await firstRowCells.count();
    expect(startCols).toBeGreaterThan(1);
    await page.getByLabel("Delete column").click();
    await expect(firstRowCells).toHaveCount(startCols - 1, { timeout: 10_000 });
  });

  test("a deleted table stays deleted after a reload", async ({ page }) => {
    await page.locator(".ProseMirror").click();
    await page.keyboard.press("Control+End");
    await page.keyboard.press("Enter");
    await page.keyboard.type("/table");
    await expect(page.locator(`${MENU} [data-slash-item="table"]`)).toBeVisible({
      timeout: 10_000,
    });
    await page.keyboard.press("Enter");
    await expect(page.locator(".ProseMirror table")).toBeVisible({
      timeout: 10_000,
    });
    // Let the debounced autosave land the table, so the reload is a real
    // round-trip rather than a no-op.
    await page.waitForTimeout(3_000);

    await page.getByTestId("delete-table").click();
    await expect(page.locator(".ProseMirror table")).toHaveCount(0);
    await page.waitForTimeout(3_000);

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator(".ProseMirror")).toBeVisible({ timeout: 20_000 });
    await expect(
      page.locator(".ProseMirror table"),
      "the table came back after reload — the removal was never saved",
    ).toHaveCount(0, { timeout: 10_000 });
  });

  // ─── Inline database ─────────────────────────────────────────────

  test("the inline-database placeholder can be dismissed", async ({ page }) => {
    await page.locator(".ProseMirror").click();
    await page.keyboard.press("Control+End");
    await page.keyboard.press("Enter");
    await page.keyboard.type("/database");
    await expect(
      page.locator(`${MENU} [data-slash-item="database"]`),
    ).toBeVisible({ timeout: 10_000 });
    await page.keyboard.press("Enter");

    const placeholder = page.locator("[data-inline-database-placeholder]");
    await expect(placeholder).toBeVisible({ timeout: 15_000 });

    // The reported dead end: nothing here led back out.
    const remove = page.getByTestId("inline-db-remove");
    await expect(
      remove,
      "the placeholder offers no way to remove itself",
    ).toBeVisible();
    await remove.click();

    await expect(placeholder).toHaveCount(0, { timeout: 10_000 });
    await expect(page.getByTestId("inline-database-node")).toHaveCount(0);
  });

  test("removing an inline database is undoable and does not delete the table", async ({
    page,
    request,
  }) => {
    // A real linked table, so "remove the embed" vs "delete the data" is
    // actually distinguishable.
    const tableResp = await request.post(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/tables`,
      {
        headers: authHeaders(),
        data: { name: `e2e-embed-${Date.now()}`, visibility: "workspace" },
      },
    );
    test.skip(
      !tableResp.ok(),
      `tables API unavailable (${tableResp.status()}) — skipping the linked-table case`,
    );
    const table = await tableResp.json();

    // Put the document straight into the linked state; driving the
    // create/link picker is covered by the placeholder test above.
    await request.patch(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents/${docId}`,
      {
        headers: authHeaders(),
        data: {
          content: {
            type: "doc",
            content: [
              { type: "paragraph", content: [{ type: "text", text: "Body" }] },
              {
                type: "inlineDatabase",
                attrs: { tableId: table.id, scope: "standalone", height: 400, collapsed: false },
              },
            ],
          },
        },
      },
    );

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator(".ProseMirror")).toBeVisible({ timeout: 20_000 });

    const remove = page.getByTestId("inline-db-remove");
    await expect(remove).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("inline-database-node")).toHaveCount(1);
    await remove.click();
    await expect(page.getByTestId("inline-database-node")).toHaveCount(0, {
      timeout: 10_000,
    });

    // It is an ordinary document edit, so the editor's own history undoes it —
    // which is what makes a one-click remove safe to offer.
    const undo = page.locator('button[aria-label="Undo"]').first();
    await expect(undo, "removing the embed left nothing on the undo stack").toBeEnabled({
      timeout: 10_000,
    });
    await undo.click();
    await expect(
      page.getByTestId("inline-database-node"),
      "removing the embed was not undoable",
    ).toHaveCount(1, { timeout: 10_000 });

    // And the table itself is untouched either way.
    const check = await request.get(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/tables/${table.id}`,
      { headers: authHeaders() },
    );
    expect(
      check.ok(),
      "removing the embed deleted the underlying table — it should only drop the embed",
    ).toBe(true);

    await request
      .delete(
        `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/tables/${table.id}`,
        { headers: authHeaders() },
      )
      .catch(() => {});
  });
});
