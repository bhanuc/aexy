/**
 * The workspace app switch, rendered.
 *
 * Its source-level guards live in `accessSettingsConsolidation.test.ts`; this
 * is the behaviour a person meets. Three things are worth pinning:
 *
 * * an admin who is not the owner sees the state and cannot change it — this
 *   layer overrules every department profile and personal override at once,
 *   so widening who can reach it is a real escalation;
 * * a toggle sends the whole map, not the one key. The endpoint replaces the
 *   settings object, so a partial body silently re-enables everything the
 *   owner had switched off;
 * * dashboard gets no switch at all, because it is where every blocked
 *   navigation is sent.
 *
 * The map the panel renders is complete: `get_workspace_app_settings` fills
 * every catalog id with `True` before merging what is stored, so a key missing
 * from the fixtures below is missing from the real response too.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceAppsPanel } from "@/components/access/WorkspaceAppsPanel";

const getAppSettings = vi.fn();
const updateAppSettings = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    workspaceApi: {
      ...(actual.workspaceApi as Record<string, unknown>),
      getAppSettings: (...args: unknown[]) => getAppSettings(...args),
      updateAppSettings: (...args: unknown[]) => updateAppSettings(...args),
    },
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderPanel(settings: Record<string, boolean>, isOwner = true) {
  getAppSettings.mockResolvedValue(settings);
  updateAppSettings.mockImplementation((_ws: string, apps: Record<string, boolean>) =>
    Promise.resolve(apps),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkspaceAppsPanel workspaceId="ws-1" isOwner={isOwner} />
    </QueryClientProvider>,
  );
}

/** The switch for one app, found by its accessible name. */
const switchFor = (label: string) => screen.getByRole("switch", { name: label });

beforeEach(() => {
  getAppSettings.mockReset();
  updateAppSettings.mockReset();
});

describe("what the panel shows", () => {
  it("reflects each app's state", async () => {
    renderPanel({ crm: true, sprints: false });

    await waitFor(() => expect(switchFor("CRM")).toBeInTheDocument());
    expect(switchFor("CRM")).toHaveAttribute("aria-checked", "true");
    expect(switchFor("Sprints")).toHaveAttribute("aria-checked", "false");
  });

  it("has no switch for the dashboard", async () => {
    renderPanel({ crm: true });

    await waitFor(() => expect(switchFor("CRM")).toBeInTheDocument());
    // `WorkspaceAppToggleGuard` redirects blocked navigation to /dashboard.
    // A workspace that has switched it off has nowhere to send anyone.
    expect(screen.queryByRole("switch", { name: "Dashboard" })).toBeNull();
  });
});

describe("changing an app", () => {
  it("sends every app, not just the one that changed", async () => {
    renderPanel({ crm: true, sprints: false, docs: true });

    await waitFor(() => expect(switchFor("CRM")).toBeInTheDocument());
    fireEvent.click(switchFor("CRM"));

    await waitFor(() => expect(updateAppSettings).toHaveBeenCalled());
    // The endpoint replaces the object. `{crm: false}` alone would drop the
    // `sprints: false` this owner had already set, turning Sprints back on as
    // a side effect of switching CRM off.
    expect(updateAppSettings).toHaveBeenCalledWith("ws-1", {
      crm: false,
      sprints: false,
      docs: true,
    });
  });
});

describe("who may change it", () => {
  it("lets a non-owner read the state but not write it", async () => {
    renderPanel({ crm: true }, false);

    await waitFor(() => expect(switchFor("CRM")).toBeInTheDocument());
    expect(switchFor("CRM")).toHaveAttribute("aria-checked", "true");
    expect(switchFor("CRM")).toBeDisabled();

    fireEvent.click(switchFor("CRM"));
    expect(updateAppSettings).not.toHaveBeenCalled();
  });

  it("says why the switches are dead", async () => {
    renderPanel({ crm: true }, false);

    await waitFor(() => expect(switchFor("CRM")).toBeInTheDocument());
    // A greyed-out control with no explanation reads as broken.
    expect(
      screen.getByText("Only the workspace owner can change which apps are on."),
    ).toBeInTheDocument();
  });
});
