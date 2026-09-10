/**
 * Sidebar preferences: favourites, pins and visit counts.
 *
 * This used to also resolve a "persona" — a preset role (developer, manager,
 * sales, …) that filtered which sections and items appeared. That layer is
 * gone. Access control decides what a person can see, department profiles set
 * the baseline, and the sidebar renders exactly that, grouped by the sections
 * in `sidebarLayouts`.
 *
 * The presets were removed because they were a second, weaker answer to a
 * question access already answers, and the two disagreed: a persona nobody had
 * chosen hid apps the workspace had granted, which is how the Operations team
 * ended up reaching Service Desk by URL. Rather than keep two systems and a
 * precedence rule between them, there is now one.
 *
 * Dashboard widget presets (`preset_type`) are a different feature and are
 * untouched.
 */

import { useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { dashboardApi, DashboardPreferences } from "@/lib/api";
import { useDashboardPreferences } from "@/hooks/useDashboardPreferences";

const MIN_VISITS_FOR_FREQUENT = 3;
/** How many favourites the sidebar shows. */
export const MAX_FAVORITES = 5;
/** Return extra candidates so the sidebar has room to drop unreachable ones. */
const MAX_FAVORITES_CANDIDATES = 15;
const PREFERENCES_KEY = ["dashboard", "preferences"];

export function useSidebarPreferences() {
  const queryClient = useQueryClient();
  const { preferences, isLoading } = useDashboardPreferences();

  // Memoised so the `|| {}` fallback doesn't mint a new object on every render
  // and invalidate every memo and callback below it.
  const pageVisits = useMemo(
    () => preferences?.sidebar_page_visits || {},
    [preferences?.sidebar_page_visits]
  );
  const pinnedItems = useMemo(
    () => preferences?.sidebar_pinned_items || [],
    [preferences?.sidebar_pinned_items]
  );

  /** Compute favorite items: pinned first, then auto-detected from visits */
  const favoriteItems = useMemo(() => {
    const favorites: Array<{ path: string; pinned: boolean }> = [];

    for (const path of pinnedItems) {
      favorites.push({ path, pinned: true });
    }

    const sortedVisits = Object.entries(pageVisits)
      .filter(([path, count]) => count >= MIN_VISITS_FOR_FREQUENT && !pinnedItems.includes(path))
      .sort((a, b) => b[1] - a[1]);

    for (const [path] of sortedVisits) {
      if (favorites.length >= MAX_FAVORITES_CANDIDATES) break;
      favorites.push({ path, pinned: false });
    }

    return favorites;
  }, [pageVisits, pinnedItems]);

  /** Toggle a path in the pinned items list — optimistic update + server persist */
  const togglePin = useCallback(
    (path: string) => {
      const current = [...pinnedItems];
      const idx = current.indexOf(path);
      if (idx >= 0) {
        current.splice(idx, 1);
      } else {
        current.push(path);
      }

      // Optimistic cache update
      const prev = queryClient.getQueryData<DashboardPreferences>(PREFERENCES_KEY);
      if (prev) {
        queryClient.setQueryData<DashboardPreferences>(PREFERENCES_KEY, {
          ...prev,
          sidebar_pinned_items: current,
        });
      }

      // Persist to server, rollback on failure, invalidate on success
      dashboardApi.updatePreferences({ sidebar_pinned_items: current }).then(() => {
        queryClient.invalidateQueries({ queryKey: PREFERENCES_KEY });
      }).catch(() => {
        if (prev) {
          queryClient.setQueryData(PREFERENCES_KEY, prev);
        }
      });
    },
    [pinnedItems, queryClient]
  );

  /** Remove a path from recent/auto-detected favorites by zeroing its visit count */
  const dismissRecent = useCallback(
    (path: string) => {
      const prev = queryClient.getQueryData<DashboardPreferences>(PREFERENCES_KEY);
      const updatedVisits = { ...(prev?.sidebar_page_visits || pageVisits) };
      delete updatedVisits[path];

      // Optimistic cache update
      if (prev) {
        queryClient.setQueryData<DashboardPreferences>(PREFERENCES_KEY, {
          ...prev,
          sidebar_page_visits: updatedVisits,
        });
      }

      // Persist to server
      dashboardApi.updatePreferences({ sidebar_page_visits: updatedVisits }).then(() => {
        queryClient.invalidateQueries({ queryKey: PREFERENCES_KEY });
      }).catch(() => {
        if (prev) {
          queryClient.setQueryData(PREFERENCES_KEY, prev);
        }
      });
    },
    [pageVisits, queryClient]
  );

  /**
   * Pin the sidebar view to an explicit choice, or pass null to go back to
   * following the department.
   *
   * Null is sent to the API as `""`, because a JSON null is indistinguishable
   * from the nulls every other untouched field carries in a PATCH.
   */
  return {
    isLoading,
    favoriteItems,
    pinnedItems,
    togglePin,
    dismissRecent,
  };
}
