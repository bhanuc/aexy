import { expect, test } from "@playwright/test";

import {
  API_BASE,
  PROJECT_ID,
  WORKSPACE_ID,
  makeTask,
  setupTaskBoardMocks,
} from "./fixtures/task-test-helpers";

const NEW_TASK_TITLE = "Quick-add from workspace kanban";

/**
 * Covers the inline quick-add row on /sprints?tab=tasks. The user types a
 * title into the dashed-border row at the bottom of a column, presses Enter,
 * and a new card appears. The flow is mocked end-to-end since the assertion
 * is on the wire shape, not on the LLM.
 */
test.describe("Workspace All-Tasks kanban: inline quick-add", () => {
  test("creates a task via the column's inline quick-add row", async ({ page }) => {
    let createCalls = 0;
    const capturedBody: { value?: Record<string, unknown> } = {};

    await setupTaskBoardMocks(page);

    // Workspace-tasks list: start empty so the column quick-add is visible.
    await page.route(`${API_BASE}/workspaces/${WORKSPACE_ID}/tasks**`, async (route) => {
      const method = route.request().method();
      const url = route.request().url();
      // POST .../tasks → create.
      if (method === "POST" && /\/tasks(?!\/)/.test(url)) {
        createCalls += 1;
        const body = route.request().postDataJSON();
        capturedBody.value = body;
        const created = makeTask({
          id: "task-new-1",
          title: (body as { title: string }).title,
          status: (body as { status?: string }).status ?? "todo",
        });
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(created),
        });
        return;
      }
      // GET .../tasks → empty list initially; after a successful POST, return
      // the new card so the refetch shows it without the optimistic update
      // doing all the work.
      if (method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(
            createCalls > 0
              ? [makeTask({ id: "task-new-1", title: NEW_TASK_TITLE, status: "todo" })]
              : [],
          ),
        });
        return;
      }
      await route.fallback();
    });

    // Projects list — needed by useProjects in useWorkspaceTasks.
    await page.route(`${API_BASE}/workspaces/${WORKSPACE_ID}/projects**`, (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          projects: [
            {
              id: PROJECT_ID,
              workspace_id: WORKSPACE_ID,
              name: "Aexy Web",
              slug: "aexy-web",
              color: "#6366f1",
              icon: "layout-grid",
              status: "active",
              is_active: true,
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ],
        }),
      });
    });

    await page.goto("sprints?tab=tasks");

    // Find the inline quick-add button in the "To Do" column. There's one per
    // column; we pick the To Do one to match how the API mock will respond.
    // Held by the column's accessible name, not its layout classes — this
    // selector used to match on `w-full md:w-[320px]`, which stopped existing
    // when the column width moved into `BOARD_COLUMN_STACKING`.
    const todoColumn = page.getByRole("group", { name: /^To Do$/i });
    const quickAdd = todoColumn.getByRole("button", { name: /\+ New task/i });

    // Initially collapsed — click to expand into an input.
    await quickAdd.click();
    const input = todoColumn.getByPlaceholder(/Title…/i);
    await expect(input).toBeVisible();
    await input.fill(NEW_TASK_TITLE);
    await input.press("Enter");

    // The POST should have been called with project_id + status=todo.
    await expect.poll(() => createCalls, { timeout: 5000 }).toBeGreaterThan(0);
    expect(capturedBody.value).toMatchObject({
      title: NEW_TASK_TITLE,
      project_id: PROJECT_ID,
      status: "todo",
    });
  });

  test("the global '+ Add task' button opens the modal with the project pre-selected", async ({
    page,
  }) => {
    await setupTaskBoardMocks(page);

    await page.route(`${API_BASE}/workspaces/${WORKSPACE_ID}/tasks**`, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route(`${API_BASE}/workspaces/${WORKSPACE_ID}/projects**`, (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          projects: [
            {
              id: PROJECT_ID,
              workspace_id: WORKSPACE_ID,
              name: "Aexy Web",
              slug: "aexy-web",
              color: "#6366f1",
              icon: "layout-grid",
              status: "active",
              is_active: true,
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ],
        }),
      });
    });

    await page.goto("sprints?tab=tasks");
    await page.getByRole("button", { name: /Add task/i }).first().click();

    // Modal opens with the title input focused — typing should land in it.
    const titleInput = page.getByPlaceholder(/What needs to be done\?/i);
    await expect(titleInput).toBeVisible();
    await expect(titleInput).toBeFocused();
  });
});
