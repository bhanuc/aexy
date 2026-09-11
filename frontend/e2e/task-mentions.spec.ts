/**
 * E2E: "@" in a task's description and in its updates composer.
 *
 * The description's list used to render below the editor with `position:
 * absolute`; on a 1280×720 screen after a long description it started at
 * y≈660 and was 211px tall, so the header was on screen and none of the names
 * were. The list is now anchored to the caret and flips above it when the
 * space below is short. These tests measure that, on that viewport, rather
 * than only asking whether the element exists.
 *
 * Live backend (needs real workspace members to offer), no LLM.
 */

import { expect, test } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
  backendOnlyReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";

test.describe.configure({ timeout: 150_000 });

const LONG_DESCRIPTION = Array.from({ length: 14 }, (_, i) => `line ${i + 1}`).join("\n");

test.describe("@-mentions in the task detail (live)", () => {
  test.skip(!backendOnlyReady(), "needs E2E_REAL_BACKEND=1 with a token and workspace");

  let projectId: string | null = null;

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await setupAiLiveAuth(page);
  });

  test.afterEach(async ({ request }) => {
    if (projectId) {
      await request
        .delete(`${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/projects/${projectId}`, {
          headers: authHeaders(),
        })
        .catch(() => {});
      projectId = null;
    }
  });

  async function openTask(page: import("@playwright/test").Page, request: import("@playwright/test").APIRequestContext) {
    const stamp = Date.now();
    const project = await (
      await request.post(`${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/projects`, {
        headers: authHeaders(),
        data: { name: `e2e-mentions-${stamp}` },
      })
    ).json();
    projectId = project.id;
    const task = await (
      await request.post(`${API_BASE}/teams/${project.id}/tasks`, {
        headers: authHeaders(),
        data: { title: `Mention me ${stamp}`, description: LONG_DESCRIPTION },
      })
    ).json();
    await page.goto(`/sprints/${project.id}/board?task=${task.id}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 30_000 });
    return { dialog, project, task };
  }

  test("the description's mention list stays on screen at the end of a long description", async ({
    page,
    request,
  }) => {
    const { dialog } = await openTask(page, request);
    const editor = dialog.locator(".ProseMirror").first();
    await editor.click();
    await page.keyboard.press("Control+End");
    await page.keyboard.type(" @");

    const list = page.getByTestId("mention-suggestions");
    await expect(list, "typing @ offered nobody").toBeVisible({ timeout: 10_000 });
    const options = list.getByTestId("mention-option");
    await expect(options.first()).toBeVisible();

    // Every offered name is inside the viewport — the whole point.
    const box = await list.boundingBox();
    expect(box, "the list has no box").toBeTruthy();
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height, "the list runs off the bottom of the screen").toBeLessThanOrEqual(720);
    const first = await options.first().boundingBox();
    expect(first!.y + first!.height).toBeLessThanOrEqual(720);

    // Arrow keys move the highlight. No mouse needed.
    const count = await options.count();
    if (count > 1) {
      await page.keyboard.press("ArrowDown");
      await expect(options.nth(1)).toHaveAttribute("aria-selected", "true");
      await page.keyboard.press("ArrowUp");
    }
    // A bare "@" then Enter is a new line, not a pick — nobody gets mentioned
    // by accident. Once something is typed, Enter picks the highlighted name.
    const name = (await options.first().textContent())!.trim();
    await page.keyboard.press("Enter");
    await expect(list).toBeHidden();
    expect(await editor.evaluate((el) => el.innerHTML)).not.toContain(`@${name}`);

    await page.keyboard.type("@" + name.slice(0, 2));
    await expect(list).toBeVisible({ timeout: 5_000 });
    const picked = (await list.getByTestId("mention-option").first().textContent())!.trim();
    await page.keyboard.press("Enter");
    await expect(list).toBeHidden();
    const html = await editor.evaluate((el) => el.innerHTML);
    expect(html).toContain(`@${picked}`);
    // The link keeps its mention href instead of being stripped to "".
    expect(html).toMatch(/href="mention:user:[0-9a-f-]{36}"/);
  });

  test("the updates composer offers @-mentions and posts the update with the name", async ({
    page,
    request,
  }) => {
    const { dialog, project, task } = await openTask(page, request);

    // Updates sit under the description now — no tab to find.
    const section = dialog.getByTestId("task-updates-section");
    await expect(section).toBeVisible();
    await expect(dialog.getByTestId("task-tab-updates")).toHaveCount(0);

    const box = section.getByTestId("work-update-input");
    await box.scrollIntoViewIfNeeded();
    await box.click();
    await page.keyboard.type("Blocked, pinging @");
    const list = page.getByTestId("work-update-mention-suggestions");
    await expect(list, "typing @ in the updates box offered nobody").toBeVisible({ timeout: 10_000 });
    const listBox = await list.boundingBox();
    expect(listBox!.y).toBeGreaterThanOrEqual(0);
    expect(listBox!.y + listBox!.height).toBeLessThanOrEqual(720);

    const name = (await list.getByTestId("mention-option").first().textContent())!.trim();
    await page.keyboard.press("Enter");
    await expect(box).toHaveValue(`Blocked, pinging @${name} `);

    await section.getByTestId("work-update-submit").click();
    await expect(section.getByTestId("work-update-item").first()).toContainText(`@${name}`, {
      timeout: 20_000,
    });

    const stored = await (
      await request.get(`${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/work-updates/task/${task.id}`, {
        headers: authHeaders(),
      })
    ).json();
    expect(stored.items.map((u: { body: string }) => u.body)).toContain(`Blocked, pinging @${name}`);
    void project;
  });
});
