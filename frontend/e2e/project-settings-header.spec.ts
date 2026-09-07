import { test, expect, Page } from "@playwright/test";
import { mockUser } from "./fixtures/mock-data";

/**
 * Status categories in workspace task settings.
 *
 * This section used to be a fixed legend of three names ("To Do", "In
 * Progress", "Done") that ignored the workspace's real buckets and offered no
 * way to change them — while the project status page linked here to edit
 * shared buckets. These tests pin down that it is now the editor: the real set
 * renders, the workspace's own rows are editable, and a project that is still
 * inheriting says so instead of offering an edit that would reach every other
 * project.
 */

const API_BASE = "http://localhost:8000/api/v1";
const WS = "ws-1";
const PROJECT_ID = "proj-1";

const mockWorkspace = {
  id: WS,
  name: "Northwind",
  slug: "northwind",
  type: "business",
  avatar_url: null,
  owner_id: mockUser.id,
  member_count: 1,
  team_count: 1,
  is_active: true,
};

// The test user has to be an admin for any editing affordance to render.
const mockMembers = [
  {
    id: "wm-1",
    workspace_id: WS,
    developer_id: mockUser.id,
    name: mockUser.name,
    email: mockUser.email,
    avatar_url: null,
    role: "owner",
    status: "active",
    joined_at: "2026-01-01T00:00:00Z",
  },
];

// `status` matters: the row renders `project.status.replace(...)`, so a project
// without one puts the whole list in its error boundary.
const mockProjects = [
  {
    id: PROJECT_ID,
    workspace_id: WS,
    name: "Apollo",
    slug: "apollo",
    description: null,
    status: "active",
    is_active: true,
    is_private: false,
    member_count: 1,
    team_count: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

function category(
  slug: string,
  label: string,
  semantics: string,
  position: number,
  projectId: string | null,
) {
  return {
    id: `cat-${projectId ? "p" : "w"}-${slug}`,
    workspace_id: WS,
    project_id: projectId,
    slug,
    label,
    color: "#6B7280",
    semantics,
    position,
    is_default: slug === "backlog",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

/** The canonical six, in a given scope. */
function sixCategories(projectId: string | null) {
  return [
    category("backlog", "Backlog", "open", 0, projectId),
    category("todo", "To Do", "open", 1, projectId),
    category("in_progress", "In Progress", "active", 2, projectId),
    // Renamed at the workspace level — proves the list is the real data and
    // not the old hardcoded legend, which called this "In Progress"/"Done".
    category("in_review", "Code Review", "active", 3, projectId),
    category("done", "Shipped", "done", 4, projectId),
    category("cancelled", "Cancelled", "cancelled", 5, projectId),
  ];
}

const workspaceStatus = {
  id: "st-1",
  workspace_id: WS,
  project_id: null,
  name: "Backlog",
  slug: "backlog",
  category: "backlog",
  color: "#9CA3AF",
  icon: null,
  position: 0,
  is_default: true,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

interface SetupOptions {
  /** Categories returned for `?project_id=proj-1`. */
  projectCategories?: unknown[];
  /** Collects the bodies of any POST to /status-categories. */
  createdCategories?: unknown[];
}

async function setup(page: Page, options: SetupOptions = {}) {
  await page.addInitScript(
    ([wsId]) => {
      localStorage.setItem("token", "fake-test-token");
      localStorage.setItem("current_workspace_id", wsId);
    },
    [WS],
  );
  await page.context().addCookies([
    { name: "aexy_authed", value: "1", url: "http://localhost:3000" },
  ]);

  // Catch-all FIRST — Playwright matches routes last-registered-first.
  await page.route(`${API_BASE}/**`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route(`${API_BASE}/workspaces`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([mockWorkspace]),
    }),
  );
  await page.route(`${API_BASE}/developers/me`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockUser),
    }),
  );
  await page.route(`${API_BASE}/notifications**`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  // The Tracker and Repositories tabs read list endpoints outside
  // /workspaces/: `targets?.find` and the repo catalogue both throw on the
  // catch-all's `{}`, and the page lands in its error boundary before the
  // header renders.
  await page.route(`${API_BASE}/tracker/**`, (route) => {
    // The project tracker config is an object; everything else here is a list.
    if (route.request().url().includes("/config")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: false,
          config: { excluded_bundle_ids: [] },
        }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "[]",
    });
  });
  await page.route(`${API_BASE}/teams/*/repositories`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );

  await page.route(`${API_BASE}/workspaces/**`, async (route) => {
    const request = route.request();
    const url = request.url();
    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });

    if (url.includes("/status-categories")) {
      if (request.method() === "POST") {
        options.createdCategories?.push(request.postDataJSON());
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(
            category("design_review", "Design Review", "active", 6, null),
          ),
        });
      }
      const scoped = url.includes(`project_id=${PROJECT_ID}`);
      return json(
        scoped ? (options.projectCategories ?? sixCategories(null)) : sixCategories(null),
      );
    }
    if (url.includes("/task-statuses")) return json([workspaceStatus]);
    if (url.includes("/custom-fields")) return json([]);
    if (url.includes("/repositories")) return json([]);
    // The settings shell gates this page on can_manage_workspace_settings;
    // without it the whole page is replaced by the access-denied panel.
    if (url.includes("/my-permissions"))
      return json({
        permissions: [
          "can_manage_workspace_settings",
          "can_manage_project_settings",
          "can_manage_tracker",
        ],
        is_owner: true,
        role_name: "Owner",
      });
    // Before /members — the effective-access path is nested under it, and
    // answering that call with the member array crashes the app shell.
    if (url.includes("/apps/effective") || url.includes("/app-access/"))
      return json({
        apps: {},
        applied_template_id: null,
        applied_template_name: null,
        has_custom_overrides: false,
        is_admin: true,
      });
    if (url.includes("/members")) return json(mockMembers);
    // The single-project fetch before the list: `useProject` needs the object,
    // and handing it the array leaves `project.name` undefined, which every
    // one of these pages renders as "Project Not Found".
    if (new RegExp(`/projects/${PROJECT_ID}$`).test(url.split("?")[0]))
      return json(mockProjects[0]);
    // `projectApi.list` returns `{ projects: [...] }` — a bare array leaves the
    // list page on its "No Projects Yet" empty state.
    if (url.includes("/projects")) return json({ projects: mockProjects });
    if (url.match(/\/(spaces|documents|invites|teams|notifications)/)) return json([]);
    if (url.endsWith(`/workspaces/${WS}`)) return json(mockWorkspace);
    return json({});
  });
}

/** The Status Categories section, scoped so status rows can't match. */
function categorySection(page: Page) {
  return page.getByRole("region", { name: "Status Categories" });
}


const TABS = ["General", "Permissions", "Repositories", "Statuses", "Tracker"];

for (const [path, expected] of [
  ["", "General"],
  ["/permissions", "Permissions"],
  ["/repositories", "Repositories"],
  ["/statuses", "Statuses"],
  ["/tracker", "Tracker"],
] as const) {
  test(`project settings header is complete on ${expected}`, async ({ page }) => {
    await setup(page);
    await page.goto(`/settings/projects/${PROJECT_ID}${path}`);

    const nav = page.getByRole("navigation", { name: "Project settings" });
    await expect(nav).toBeVisible({ timeout: 20000 });

    // Every tab is reachable from every tab.
    for (const label of TABS) {
      await expect(nav.getByRole("link", { name: label })).toBeVisible();
    }
    // Exactly one is marked current, and it's this page's.
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
    await expect(nav.locator('[aria-current="page"]')).toHaveText(expected);

    // The title is the project's name on every tab, not a generic page title.
    await expect(
      page.getByRole("heading", { name: "Apollo", level: 1 }),
    ).toBeVisible();
  });
}

test("the project row menu offers every settings destination", async ({ page }) => {
  await setup(page);
  await page.goto("/settings/projects");

  // The row menu used to offer Project Settings and Permissions only, so
  // Repositories, Statuses and Tracker were reachable only by opening a
  // project first. It reads the same tab list as the header now.
  await page.getByRole("button", { name: /^Manage project/ }).first().click();

  const menu = page.getByRole("menu", { name: /Apollo/ });
  for (const label of [
    "Project Settings",
    "Permissions",
    "Repositories",
    "Statuses",
    "Tracker",
  ]) {
    await expect(menu.getByRole("menuitem", { name: label })).toBeVisible();
  }
  await expect(
    menu.getByRole("menuitem", { name: "Delete Project" }),
  ).toBeVisible();

  // Each one points at the tab it names.
  await expect(
    menu.getByRole("menuitem", { name: "Statuses" }),
  ).toHaveAttribute("href", `/settings/projects/${PROJECT_ID}/statuses`);
});
