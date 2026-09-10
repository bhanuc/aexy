"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Building2,
  Clock,
  Contact,
  Database,
  FileText,
  Ghost,
  Inbox,
  Mail,
  ScrollText,
  Shield,
  Sparkles,
  Target,
  UserCog,
  Users,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { SettingsPage } from "./SettingsPrimitives";

/**
 * Header for a settings area made of several sibling pages.
 *
 * Some of these areas had no shared navigation at all, and four of their pages
 * were dead ends: `/settings/access/{templates,logs,gmail-exclusions}` and
 * `/settings/identity/admin` have no sidebar entry, no breadcrumbs and no link
 * back, so once you were on one the browser's back button was the only exit.
 * Service Desk's nine pages were all reachable from the sidebar but named
 * themselves from nine differently-shaped keys, so the area read as nine
 * unrelated screens.
 *
 * One definition per area, below. The active tab is derived from the pathname
 * (longest matching href wins, so a child route resolves to itself rather than
 * to the area root), and the breadcrumb trail is built from the same data — a
 * page cannot disagree with the strip above it.
 *
 * `ProjectSettingsPage` stays separate: its title is the project's name, which
 * has to be fetched, and its tabs hang off a dynamic route segment.
 */

interface GroupTab {
  key: string;
  /** Key under `settingsGroups.<group>.tabs`. */
  labelKey: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

interface GroupDef {
  /** Key under `settingsGroups`; also supplies the area's own title. */
  key: string;
  /** The area root, used as the breadcrumb parent. */
  href: string;
  tabs: GroupTab[];
}

const SD = "/settings/service-desk";

export const SETTINGS_GROUPS = {
  access: {
    key: "access",
    href: "/settings/access",
    tabs: [
      { key: "overview", labelKey: "overview", href: "/settings/access", icon: Shield },
      {
        key: "templates",
        labelKey: "templates",
        href: "/settings/access/templates",
        icon: FileText,
      },
      {
        key: "logs",
        labelKey: "logs",
        href: "/settings/access/logs",
        icon: ScrollText,
      },
      {
        key: "gmailExclusions",
        labelKey: "gmailExclusions",
        href: "/settings/access/gmail-exclusions",
        icon: Mail,
      },
    ],
  },
  identity: {
    key: "identity",
    href: "/settings/identity",
    tabs: [
      { key: "overview", labelKey: "overview", href: "/settings/identity", icon: UserCog },
      {
        key: "ghosts",
        labelKey: "ghosts",
        href: "/settings/identity/admin",
        icon: Ghost,
      },
    ],
  },
  serviceDesk: {
    key: "serviceDesk",
    href: `${SD}/identity`,
    tabs: [
      { key: "identity", labelKey: "identity", href: `${SD}/identity`, icon: Target },
      { key: "intake", labelKey: "intake", href: `${SD}/intake`, icon: Inbox },
      { key: "mailboxes", labelKey: "mailboxes", href: `${SD}/mailboxes`, icon: Mail },
      {
        key: "stakeholders",
        labelKey: "stakeholders",
        href: `${SD}/stakeholders`,
        icon: Contact,
      },
      {
        key: "masterData",
        labelKey: "masterData",
        href: `${SD}/master-data`,
        icon: Database,
      },
      { key: "hours", labelKey: "hours", href: `${SD}/hours`, icon: Clock },
      { key: "scorecard", labelKey: "scorecard", href: `${SD}/scorecard`, icon: Users },
      { key: "digest", labelKey: "digest", href: `${SD}/digest`, icon: Building2 },
      { key: "ai", labelKey: "ai", href: `${SD}/ai`, icon: Sparkles },
    ],
  },
} satisfies Record<string, GroupDef>;

export type SettingsGroupKey = keyof typeof SETTINGS_GROUPS;

/** Longest matching href wins, so a child route resolves to itself. */
function useActiveTab(group: GroupDef): GroupTab | undefined {
  const pathname = usePathname() ?? "";
  return group.tabs
    .filter((t) => pathname === t.href || pathname.startsWith(t.href + "/"))
    .sort((a, b) => b.href.length - a.href.length)[0];
}

export function SettingsGroupTabs({ group }: { group: SettingsGroupKey }) {
  const def = SETTINGS_GROUPS[group];
  const t = useTranslations(`settingsGroups.${def.key}`);
  const active = useActiveTab(def);

  return (
    <nav
      aria-label={t("navLabel")}
      className="flex flex-wrap gap-2 mb-8"
    >
      {def.tabs.map(({ key, labelKey, href, icon: Icon }) => {
        const isActive = key === active?.key;
        return (
          <Link
            key={key}
            href={href}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition",
              isActive
                ? "bg-primary-600 text-white"
                : "bg-muted text-foreground hover:bg-accent",
            )}
          >
            <Icon className="h-4 w-4" />
            {t(`tabs.${labelKey}`)}
          </Link>
        );
      })}
    </nav>
  );
}

export interface SettingsGroupPageProps {
  group: SettingsGroupKey;
  /** The page's own title. Falls back to the active tab's label. */
  title?: string;
  description?: string;
  actions?: React.ReactNode;
  width?: "form" | "wide";
  children: React.ReactNode;
}

export function SettingsGroupPage({
  group,
  title,
  description,
  actions,
  width = "wide",
  children,
}: SettingsGroupPageProps) {
  const def = SETTINGS_GROUPS[group];
  const t = useTranslations(`settingsGroups.${def.key}`);
  const tc = useTranslations("common");
  const active = useActiveTab(def);

  const areaLabel = t("title");
  const tabLabel = active ? t(`tabs.${active.labelKey}`) : areaLabel;
  const isRoot = active?.href === def.href;

  return (
    <SettingsPage
      title={title ?? tabLabel}
      description={description}
      actions={actions}
      width={width}
      breadcrumbs={[
        { label: tc("settings"), href: "/settings" },
        // At the area root the area *is* the leaf; deeper in, it links back so
        // the trail isn't a dead end — which is the whole point here.
        ...(isRoot
          ? [{ label: areaLabel }]
          : [{ label: areaLabel, href: def.href }, { label: tabLabel }]),
      ]}
    >
      <SettingsGroupTabs group={group} />
      {children}
    </SettingsPage>
  );
}
