"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, FolderGit2, Settings, Shield, Workflow } from "lucide-react";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { useWorkspace } from "@/hooks/useWorkspace";
import { useProject } from "@/hooks/useProjects";
import { SettingsPage } from "./SettingsPrimitives";

/**
 * The one header every project settings tab renders.
 *
 * Each of these pages used to hand-roll its own title, breadcrumbs and tab
 * strip, and they had drifted apart: General and Tracker listed all five tabs,
 * Permissions and Statuses listed three (no way to reach Repositories or
 * Tracker from either), and Repositories had no strip at all. The titles
 * disagreed too — some showed the project's name, others a generic page title,
 * so the same project looked like three different places. Tracker even
 * labelled its own tab from a translation key, so the strip read "Tracker" on
 * four pages and something else on the fifth.
 *
 * The tab list lives here once. The active tab is derived from the pathname
 * rather than passed in, so a page cannot mark the wrong one.
 *
 * Not included: `oncall`. It sits under this route but reads `projectId` as a
 * *team* id (`useTeam`), so it is a team page wearing a project URL — putting
 * it in this strip would offer a tab that resolves to a different entity.
 */

export type ProjectSettingsTab =
  | "general"
  | "permissions"
  | "repositories"
  | "statuses"
  | "tracker";

export interface ProjectSettingsTabDef {
  key: ProjectSettingsTab;
  /** Key under the `settingsProjects` namespace. */
  labelKey: string;
  /**
   * Key to use in a row menu, where "General" reads as nothing in particular.
   * Falls back to `labelKey`.
   */
  menuLabelKey?: string;
  /** Appended to `/settings/projects/<id>`; "" is the General tab. */
  segment: string;
  icon: React.ComponentType<{ className?: string }>;
}

/**
 * Every project settings destination, in tab order.
 *
 * Exported because the project list's row menu offers the same destinations —
 * it was offering two of these five, so the menu and the tab strip disagreed
 * about what a project even has. Both read this now.
 */
export const PROJECT_SETTINGS_TABS: ProjectSettingsTabDef[] = [
  {
    key: "general",
    labelKey: "tabs.general",
    menuLabelKey: "tabs.projectSettings",
    segment: "",
    icon: Settings,
  },
  {
    key: "permissions",
    labelKey: "tabs.permissions",
    segment: "/permissions",
    icon: Shield,
  },
  {
    key: "repositories",
    labelKey: "tabs.repositories",
    segment: "/repositories",
    icon: FolderGit2,
  },
  { key: "statuses", labelKey: "tabs.statuses", segment: "/statuses", icon: Workflow },
  { key: "tracker", labelKey: "tabs.tracker", segment: "/tracker", icon: Activity },
];

export function projectSettingsHref(
  projectId: string,
  tab: ProjectSettingsTabDef,
): string {
  return `/settings/projects/${projectId}${tab.segment}`;
}

const TABS = PROJECT_SETTINGS_TABS;

/** Which tab the current URL is on. Falls back to General. */
function useActiveTab(projectId: string): ProjectSettingsTab {
  const pathname = usePathname() ?? "";
  const base = `/settings/projects/${projectId}`;
  if (!pathname.startsWith(base)) return "general";
  // Trailing slash normalized so `/statuses/` matches `/statuses`.
  const rest = pathname.slice(base.length).replace(/\/$/, "");
  return TABS.find((t) => t.segment === rest)?.key ?? "general";
}

export function ProjectSettingsTabs({ projectId }: { projectId: string }) {
  const t = useTranslations("settingsProjects");
  const active = useActiveTab(projectId);

  return (
    <nav aria-label={t("tabs.navLabel")} className="flex flex-wrap gap-2 mb-8">
      {TABS.map(({ key, labelKey, segment, icon: Icon }) => {
        const isActive = key === active;
        return (
          <Link
            key={key}
            href={`/settings/projects/${projectId}${segment}`}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition",
              isActive
                ? "bg-primary-600 text-white"
                : "bg-muted text-foreground hover:bg-accent",
            )}
          >
            <Icon className="h-4 w-4" />
            {t(labelKey)}
          </Link>
        );
      })}
    </nav>
  );
}

export interface ProjectSettingsPageProps {
  projectId: string;
  /** The per-tab subtitle. The title is always the project's name. */
  description?: string;
  actions?: React.ReactNode;
  width?: "form" | "wide";
  children: React.ReactNode;
}

export function ProjectSettingsPage({
  projectId,
  description,
  actions,
  width = "wide",
  children,
}: ProjectSettingsPageProps) {
  const t = useTranslations("settingsProjects");
  const { currentWorkspaceId } = useWorkspace();
  // Deduped by react-query against the page's own `useProject` call.
  const { project } = useProject(currentWorkspaceId, projectId);
  const active = useActiveTab(projectId);

  // Named "Project" only in the gap before the fetch resolves — every caller
  // renders a skeleton or a not-found state until it does.
  const name = project?.name ?? "Project";
  const activeTab = TABS.find((tab) => tab.key === active);
  const tabLabel = t(activeTab?.labelKey ?? "tabs.general");

  return (
    <SettingsPage
      title={name}
      description={description}
      actions={actions}
      width={width}
      breadcrumbs={[
        { label: t("breadcrumbs.settings"), href: "/settings" },
        { label: t("breadcrumbs.projects"), href: "/settings/projects" },
        // On General the project *is* the leaf; deeper tabs make it a link
        // back so the name isn't a dead end two levels down.
        ...(active === "general"
          ? [{ label: name }]
          : [
              { label: name, href: `/settings/projects/${projectId}` },
              { label: tabLabel },
            ]),
      ]}
    >
      <ProjectSettingsTabs projectId={projectId} />
      {children}
    </SettingsPage>
  );
}
