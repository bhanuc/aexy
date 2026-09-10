/**
 * E2E: "Embed Module Data" can actually see module data.
 *
 * The inline-database picker splits the workspace's tables into two buckets —
 * linkable tables (`standalone`/`document`) and module data (`crm`/`project`).
 * `useTables` hardcoded its query to `scope=standalone`, so the second bucket
 * filtered a list that could never contain a match: the picker showed "No
 * module data available. Create CRM objects or project tables first." however
 * many CRM objects the workspace had, and creating one did not help.
 *
 * The same hardcoding meant a document embedding a CRM object could not
 * resolve its name and rendered "Database".
 *
 * Note what this does NOT cover: projects. Nothing in the backend writes
 * `scope='project'` — a project is not a table — so projects will not appear
 * here regardless. That is a missing feature, not a filter to widen, and the
 * empty-state copy promising "project tables" is still wrong.
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

const MENU = "[data-slash-menu]";
const WS = () => REAL_BACKEND_WORKSPACE_ID;

async function createCrmObject(request: APIRequestContext, name: string) {
  // CRM's own create path omits `scope`, so the row lands on the model default
  // of 'crm' — which is exactly the bucket the picker is meant to show.
  const resp = await request.post(`${API_BASE}/workspaces/${WS()}/crm/objects`, {
    headers: authHeaders(),
    data: { name, plural_name: `${name}s` },
  });
  expect(resp.ok(), `CRM object create failed: ${resp.status()}`).toBe(true);
  const obj = await resp.json();
  expect(obj.scope, "CRM objects are expected to carry scope='crm'").toBe("crm");
  return obj;
}

test.describe("Docs inline database / Embed Module Data (live)", () => {
  let docId: string | null = null;
  let crmId: string | null = null;
  let crmName = "";

  test.beforeEach(async ({ page, request }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);

    crmName = `e2e-embed-crm-${Date.now()}`;
    crmId = (await createCrmObject(request, crmName)).id;

    const resp = await request.post(
      `${API_BASE}/workspaces/${WS()}/documents`,
      {
        headers: authHeaders(),
        data: {
          title: `e2e-embed-${Date.now()}`,
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
    expect(resp.ok()).toBe(true);
    docId = (await resp.json()).id;

    await page.setViewportSize({ width: 1600, height: 1000 });
  });

  test.afterEach(async ({ request }) => {
    if (docId) {
      await request
        .delete(`${API_BASE}/workspaces/${WS()}/documents/${docId}`, {
          headers: authHeaders(),
        })
        .catch(() => {});
      docId = null;
    }
    if (crmId) {
      await request
        .delete(`${API_BASE}/workspaces/${WS()}/tables/${crmId}`, {
          headers: authHeaders(),
        })
        .catch(() => {});
      crmId = null;
    }
  });

  test("the module picker lists a CRM object instead of claiming there is none", async ({
    page,
  }) => {
    await page.goto(`/docs/${docId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    await expect(page.locator(".ProseMirror")).toBeVisible({ timeout: 60_000 });

    await page.locator(".ProseMirror").click();
    await page.keyboard.press("Control+End");
    await page.keyboard.press("Enter");
    await page.keyboard.type("/database");
    await expect(page.locator(`${MENU} [data-slash-item="database"]`)).toBeVisible({
      timeout: 10_000,
    });
    await page.keyboard.press("Enter");

    const placeholder = page.locator("[data-inline-database-placeholder]");
    await expect(placeholder).toBeVisible({ timeout: 20_000 });
    await placeholder.getByRole("button", { name: /Embed Module/i }).click();

    await expect(
      page.getByText(/No module data available/i),
      "the picker still reports no module data although a CRM object exists",
    ).toHaveCount(0, { timeout: 20_000 });
    await expect(
      page.getByRole("button", { name: new RegExp(crmName, "i") }),
      "the CRM object is missing from the module picker",
    ).toBeVisible({ timeout: 20_000 });
  });

  test("an embedded CRM object renders its own name, not 'Database'", async ({
    page,
    request,
  }) => {
    await request.patch(
      `${API_BASE}/workspaces/${WS()}/documents/${docId}`,
      {
        headers: authHeaders(),
        data: {
          content: {
            type: "doc",
            content: [
              { type: "paragraph", content: [{ type: "text", text: "Body" }] },
              {
                type: "inlineDatabase",
                attrs: {
                  tableId: crmId,
                  scope: "crm",
                  height: 400,
                  collapsed: false,
                },
              },
            ],
          },
        },
      },
    );

    await page.goto(`/docs/${docId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    const node = page.getByTestId("inline-database-node");
    await expect(node).toBeVisible({ timeout: 60_000 });

    // The name comes from resolving tableId against the fetched table list —
    // impossible while that list was pinned to standalone scope.
    await expect(
      node.getByText(crmName),
      "the embed could not resolve its CRM object and fell back to 'Database'",
    ).toBeVisible({ timeout: 20_000 });
  });
});
