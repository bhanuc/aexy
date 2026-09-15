import { test, expect, Page } from "@playwright/test";
import { mockUser } from "./fixtures/mock-data";

/**
 * The invite dialog rendered its fields outside its own panel.
 *
 * Two compounding causes, both `min-width: auto`:
 *
 * 1. The team row is a flex row of two <select>s. A native select takes its
 *    intrinsic width from its widest option, so the longest team name in the
 *    workspace decided how wide that row insisted on being — and a flex item
 *    never shrinks below that on its own.
 * 2. `DialogContent` is a grid, so the <form> is a grid item that expands to
 *    its own min-content. That is why *every* w-full field rendered wider than
 *    the panel, not just the row that caused it.
 *
 * The panel itself stays at `max-w-md`, so the fields drew over the page
 * behind it. Both fixes are needed: without the row's `min-w-0` the row still
 * overflows the form by the difference, and without the dialog's the whole
 * form widens again.
 *
 * Asserted in a browser rather than a unit test because nothing but a real
 * layout engine computes min-content — jsdom reports every width as 0. The
 * second select only exists once a team is picked, which is why this test
 * picks one.
 */

const API_BASE = "http://localhost:8000/api/v1";

const mockWorkspace = {
  id: "ws-1",
  name: "Northwind",
  slug: "northwind",
  type: "business",
  avatar_url: null,
  owner_id: "test-user-123",
  member_count: 2,
  team_count: 2,
  is_active: true,
};

// The caller has to be an admin for the Invite button to render at all.
const mockMembers = [
  {
    id: "wm-1",
    workspace_id: "ws-1",
    developer_id: "test-user-123",
    name: "Test Developer",
    email: "test@example.com",
    avatar_url: null,
    role: "owner",
    role_id: null,
    role_name: null,
    status: "active",
    joined_at: "2026-07-01T00:00:00Z",
  },
];

// Long names on purpose: these are what used to decide the dialog's width.
const mockDepartments = [
  {
    id: "d-1", workspace_id: "ws-1", name: "Engineering", slug: "engineering",
    description: null, function_key: "engineering", parent_id: null,
    path: "/engineering/", depth: 0, position: 0, head_id: null,
    cost_center: null, budget_amount: null, budget_currency: null,
    headcount_planned: null, headcount_actual: null, location: null,
    timezone: null, is_active: true, member_count: 4, has_access_profile: false,
    created_at: "2026-07-01T00:00:00Z", updated_at: "2026-07-01T00:00:00Z",
  },
];

// A team whose name is longer than a short acronym. A native <select> takes
// its intrinsic width from its widest option, so the longest team name in the
// workspace is what decides how wide this control wants to be — and that is
// what pushed the form past the panel.
const mockTeams = [
  { id: "t-1", workspace_id: "ws-1", name: "VLTS", slug: "vlts",
    type: "internal", description: null, is_active: true, member_count: 3 },
  { id: "t-2", workspace_id: "ws-1", name: "Platform Infrastructure & Reliability",
    slug: "platform-infra", type: "internal", description: null,
    is_active: true, member_count: 7 },
];

async function setup(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("token", "fake-test-token");
    localStorage.setItem("current_workspace_id", "ws-1");
  });
  await page.context().addCookies([
    { name: "aexy_authed", value: "1", url: "http://localhost:3000" },
  ]);

  // Catch-all FIRST (Playwright checks routes last-registered-first).
  await page.route(`${API_BASE}/**`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route(`${API_BASE}/workspaces`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([mockWorkspace]) }),
  );
  await page.route(`${API_BASE}/developers/me`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(mockUser) }),
  );
  await page.route(`${API_BASE}/notifications**`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(`${API_BASE}/workspaces/**`, (route) => {
    const url = route.request().url();
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

    // Order matters: /app-access/preview is a POST with its own shape, and the
    // broader /app-access/ arm below would otherwise swallow it.
    if (url.includes("/app-access/preview"))
      return json({
        enabled_app_names: ["AI Agents", "Dashboard", "Sprints", "Tickets"],
        baseline: "role_fallback",
        baseline_detail: null,
      });
    if (url.includes("/apps/effective") || url.includes("/app-access/"))
      return json({
        apps: {},
        applied_template_id: null,
        applied_template_name: null,
        has_custom_overrides: false,
        is_admin: true,
      });
    // The settings shell gates /settings/organization on can_manage_org, and
    // renders "You don't have access to this page" without it.
    if (url.match(/\/my-permissions(\?|$)/))
      return json({
        permissions: [
          "can_manage_org",
          "can_view_projects",
          "can_invite_members",
          "can_manage_workspace_settings",
        ],
        is_owner: true,
        role_name: "Owner",
      });
    if (url.includes("/organization/departments")) return json(mockDepartments);
    if (url.includes("/organization/people")) return json([]);
    if (url.match(/\/teams(\?|$)/)) return json(mockTeams);
    if (url.match(/\/members(\?|$)/)) return json(mockMembers);
    if (url.match(/\/invites(\?|$)/)) return json([]);
    if (url.match(/\/(spaces|documents|task-statuses|projects|roles|teams)/)) return json([]);
    if (url.endsWith("/workspaces/ws-1")) return json(mockWorkspace);
    return json({});
  });
}

test.describe("Invite dialog layout", () => {
  // 620px, not the default 1280. The panel is `w-[calc(100%-2rem)] max-w-md`,
  // so above ~480px of window it is pinned at 448px and wider than nothing it
  // contains. The overflow appears once the window itself is the constraint —
  // a half-width browser window, which is where this was reported.
  for (const width of [420, 1280]) {
    test(`keeps its fields inside the panel at ${width}px`, async ({ page }) => {
      await setup(page);
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/settings/organization");

      await page.getByRole("button", { name: /invite member/i }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();

      // Pick the long-named team: that reveals the role-in-team select beside
      // it, and the pair is what used to push the form past the panel.
      const teamSelect = dialog.locator("select").last();
      await teamSelect.selectOption({ label: "Platform Infrastructure & Reliability" });
      await expect(dialog.locator("select")).toHaveCount(4);

      const panel = (await dialog.boundingBox())!;
      for (const field of await dialog.locator("input, select, button").all()) {
        const box = await field.boundingBox();
        if (!box || box.width === 0) continue; // hidden control
        expect(
          box.x + box.width,
          `${await field.evaluate((el) => el.tagName)} runs past the right edge`,
        ).toBeLessThanOrEqual(panel.x + panel.width + 1);
        expect(box.x).toBeGreaterThanOrEqual(panel.x - 1);
      }

      // And the panel carries no hidden horizontal scroll of its own.
      expect(await dialog.evaluate((el) => el.scrollWidth - el.clientWidth))
        .toBeLessThanOrEqual(1);
    });
  }

  test("scrolls rather than running off the viewport when short", async ({ page }) => {
    await setup(page);
    await page.setViewportSize({ width: 1280, height: 600 });
    await page.goto("/settings/organization");

    await page.getByRole("button", { name: /invite member/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const box = await dialog.boundingBox();
    const viewport = page.viewportSize()!;
    expect(box!.y).toBeGreaterThanOrEqual(-1);
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height + 1);

    // The submit button is reachable — the point of the scroll container.
    await expect(page.getByRole("button", { name: /send invite/i })).toBeVisible();
  });
});
