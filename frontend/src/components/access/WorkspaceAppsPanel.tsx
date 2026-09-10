"use client";

import { Layers, Loader2, ToggleLeft, ToggleRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { APP_CATALOG } from "@/config/appDefinitions";
import { useWorkspaceAppSettings } from "@/hooks/useWorkspace";

/**
 * Which apps exist for this workspace at all.
 *
 * The outermost layer of access resolution: `workspace_disabled` is checked
 * before the role fallback, before the department profile and before anybody's
 * personal override, so an app switched off here cannot be granted back by any
 * of them. It lived on the Organization page, three layers away from the ones
 * it overrules, which meant an admin could spend a while giving a department an
 * app that was never going to resolve.
 *
 * Dashboard is absent on purpose — it is the landing page, and a workspace
 * whose owner can switch it off has a broken front door.
 */

const TOGGLEABLE_APPS = Object.entries(APP_CATALOG)
  .filter(([id]) => id !== "dashboard")
  .map(([id, app]) => ({ id, label: app.name, description: app.description }));

export function WorkspaceAppsPanel({
  workspaceId,
  isOwner,
}: {
  workspaceId: string;
  /** Only the owner may change these; everyone else reads them. */
  isOwner: boolean;
}) {
  const t = useTranslations("settingsAccess.workspaceApps");
  const tc = useTranslations("common");
  const { appSettings, isLoading, updateAppSettings, isUpdating } =
    useWorkspaceAppSettings(workspaceId);
  // The hook falls back to `{}` before the fetch lands, which narrows away the
  // interface's index signature. Same widening `WorkspaceAppToggleGuard` does.
  const settings: Record<string, boolean> = appSettings;

  const handleToggle = async (appId: string) => {
    if (!isOwner) return;
    await updateAppSettings({ ...settings, [appId]: !settings[appId] });
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden />
        <span className="sr-only">{tc("loading")}</span>
      </div>
    );
  }

  return (
    <section aria-labelledby="workspace-apps-heading" className="bg-card rounded-xl overflow-hidden">
      <div className="p-4 border-b border-border flex items-center gap-3">
        <Layers className="h-5 w-5 text-muted-foreground" aria-hidden />
        <div>
          <h3 id="workspace-apps-heading" className="text-foreground font-medium">
            {t("heading")}
          </h3>
          <p className="text-muted-foreground text-sm">{t("subtitle")}</p>
        </div>
      </div>
      <div className="p-4 space-y-3">
        {TOGGLEABLE_APPS.map(({ id, label, description }) => {
          const enabled = settings[id];
          return (
            <div
              key={id}
              className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-3 bg-muted/30 rounded-lg"
            >
              <div>
                <div className="text-foreground font-medium">{label}</div>
                <div className="text-muted-foreground text-sm">{description}</div>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={Boolean(enabled)}
                aria-label={label}
                onClick={() => handleToggle(id)}
                disabled={isUpdating || !isOwner}
                className={`p-1 rounded-full transition ${
                  !isOwner ? "opacity-50 cursor-not-allowed" : "hover:bg-accent"
                }`}
                title={
                  isOwner
                    ? t("toggleTitle", {
                        action: enabled ? tc("disable") : tc("enable"),
                        label,
                      })
                    : t("ownerOnlyTitle")
                }
              >
                {enabled ? (
                  <ToggleRight className="h-8 w-8 text-green-400" aria-hidden />
                ) : (
                  <ToggleLeft className="h-8 w-8 text-muted-foreground" aria-hidden />
                )}
              </button>
            </div>
          );
        })}
      </div>
      {!isOwner && (
        <div className="px-4 pb-4">
          <p className="text-xs text-muted-foreground">{t("ownerOnly")}</p>
        </div>
      )}
    </section>
  );
}
