"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import {
  platformAdminApi,
  AdminDashboardStats,
  PlatformOverview,
  PlatformSnapshotRefresh,
  PlatformStatsSeries,
  PaginatedAdminEmailLogs,
  PaginatedAdminNotifications,
  PaginatedAdminWorkspaces,
  PaginatedAdminUsers,
  EmailListParams,
  AdminEmailLog,
  ResendEmailResponse,
} from "@/lib/api";

/**
 * Hook to check if the current user is a platform admin.
 *
 * Admin access is per-email (ADMIN_EMAILS) — no platform-org membership
 * required. platformOrgId is still returned for workspace context.
 */
export function useAdmin() {
  const { user, isLoading: isAuthLoading } = useAuth();

  const {
    data: adminCheck,
    isLoading: isCheckLoading,
    error,
  } = useQuery({
    queryKey: ["admin-check"],
    queryFn: () => platformAdminApi.checkAdmin(),
    enabled: !!user && !isAuthLoading,
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
    retry: 1,
  });

  return {
    isAdmin: adminCheck?.is_admin ?? false,
    platformOrgId: adminCheck?.platform_org_id ?? null,
    isLoading: isAuthLoading || isCheckLoading,
    error,
  };
}

/**
 * Hook to fetch admin dashboard statistics.
 */
export function useAdminDashboardStats() {
  const { isAdmin } = useAdmin();

  return useQuery<AdminDashboardStats>({
    queryKey: ["admin-dashboard-stats"],
    queryFn: () => platformAdminApi.getDashboardStats(),
    enabled: isAdmin,
    staleTime: 60 * 1000, // Cache for 1 minute
    refetchInterval: 60 * 1000, // Refresh every minute
  });
}

/**
 * Hook to fetch admin email logs.
 */
export function useAdminEmailLogs(params?: EmailListParams) {
  const { isAdmin } = useAdmin();

  return useQuery<PaginatedAdminEmailLogs>({
    queryKey: ["admin-email-logs", params],
    queryFn: () => platformAdminApi.getEmailLogs(params),
    enabled: isAdmin,
    staleTime: 30 * 1000, // Cache for 30 seconds
  });
}

/**
 * Hook to fetch a single email log.
 */
export function useAdminEmailLog(emailId: string | null) {
  const { isAdmin } = useAdmin();

  return useQuery<AdminEmailLog>({
    queryKey: ["admin-email-log", emailId],
    queryFn: () => platformAdminApi.getEmailLog(emailId!),
    enabled: isAdmin && !!emailId,
  });
}

/**
 * Hook to resend a failed email.
 */
export function useResendEmail() {
  const queryClient = useQueryClient();

  return useMutation<ResendEmailResponse, Error, string>({
    mutationFn: (emailId: string) => platformAdminApi.resendEmail(emailId),
    onSuccess: () => {
      // Invalidate email logs to refresh the list
      queryClient.invalidateQueries({ queryKey: ["admin-email-logs"] });
      queryClient.invalidateQueries({ queryKey: ["admin-dashboard-stats"] });
    },
  });
}

/**
 * Hook to fetch admin notifications.
 */
export function useAdminNotifications(params?: {
  page?: number;
  per_page?: number;
  event_type?: string;
  search?: string;
}) {
  const { isAdmin } = useAdmin();

  return useQuery<PaginatedAdminNotifications>({
    queryKey: ["admin-notifications", params],
    queryFn: () => platformAdminApi.getNotifications(params),
    enabled: isAdmin,
    staleTime: 30 * 1000,
  });
}

/**
 * Hook to fetch admin workspaces.
 */
export function useAdminWorkspaces(params?: {
  page?: number;
  per_page?: number;
  search?: string;
  plan_tier?: string;
}) {
  const { isAdmin } = useAdmin();

  return useQuery<PaginatedAdminWorkspaces>({
    queryKey: ["admin-workspaces", params],
    queryFn: () => platformAdminApi.getWorkspaces(params),
    enabled: isAdmin,
    staleTime: 60 * 1000,
  });
}

/**
 * Hook to fetch admin users.
 */
export function useAdminUsers(params?: {
  page?: number;
  per_page?: number;
  search?: string;
}) {
  const { isAdmin } = useAdmin();

  return useQuery<PaginatedAdminUsers>({
    queryKey: ["admin-users", params],
    queryFn: () => platformAdminApi.getUsers(params),
    enabled: isAdmin,
    staleTime: 60 * 1000,
  });
}


/**
 * Headline platform numbers, each against what it was `comparisonDays` ago.
 *
 * Served from the daily snapshot, so it is cheap and — unlike everything it
 * replaces — can say whether a figure is going up.
 */
export function usePlatformOverview(comparisonDays = 30) {
  const { isAdmin } = useAdmin();

  return useQuery<PlatformOverview>({
    queryKey: ["platform-stats-overview", comparisonDays],
    queryFn: () => platformAdminApi.getStatsOverview(comparisonDays),
    enabled: isAdmin,
    staleTime: 5 * 60 * 1000,
  });
}

/** The daily series behind the growth and revenue charts. */
export function usePlatformStatsSeries(days = 90) {
  const { isAdmin } = useAdmin();

  return useQuery<PlatformStatsSeries>({
    queryKey: ["platform-stats-series", days],
    queryFn: () => platformAdminApi.getStatsSeries(days),
    enabled: isAdmin,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Recompute today's snapshot now. The schedule writes one a day; this is for
 * the first run, and for an admin who has just changed a plan and wants to
 * see it without waiting until tomorrow.
 */
export function useRefreshPlatformStats() {
  const queryClient = useQueryClient();

  return useMutation<PlatformSnapshotRefresh, unknown, number | undefined>({
    mutationFn: (backfillDays) => platformAdminApi.refreshStats(backfillDays ?? 0),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-stats-overview"] });
      queryClient.invalidateQueries({ queryKey: ["platform-stats-series"] });
      // The billing totals card reads the same snapshot.
      queryClient.invalidateQueries({ queryKey: ["platform-billing-totals"] });
    },
  });
}
