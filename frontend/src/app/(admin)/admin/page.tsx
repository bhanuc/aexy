"use client";

import Link from "next/link";
import {
  AlertCircle,
  AlertTriangle,
  Bell,
  Building2,
  CheckCircle2,
  ChevronRight,
  Loader2,
  Mail,
  RefreshCw,
  TrendingUp,
  Users,
  XCircle,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { formatDistanceToNow } from "date-fns";

import {
  useAdminEmailLogs,
  usePlatformOverview,
  useRefreshPlatformStats,
} from "@/hooks/useAdmin";
import {
  BreakdownList,
  KpiCard,
  formatCents,
  formatCount,
} from "@/components/admin/platformStats";

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { color: string; icon: React.ElementType }> = {
    sent: { color: "text-emerald-400 bg-emerald-400/10", icon: CheckCircle2 },
    delivered: { color: "text-emerald-400 bg-emerald-400/10", icon: CheckCircle2 },
    failed: { color: "text-red-400 bg-red-400/10", icon: XCircle },
    bounced: { color: "text-orange-400 bg-orange-400/10", icon: AlertCircle },
    pending: { color: "text-yellow-400 bg-yellow-400/10", icon: AlertCircle },
  };
  const { color, icon: Icon } = config[status] || config.pending;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs ${color}`}>
      <Icon className="h-3 w-3" />
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

export default function AdminDashboardPage() {
  const t = useTranslations("admin");
  const { data: overview, isLoading, error } = usePlatformOverview(30);
  const refresh = useRefreshPlatformStats();
  const { data: recentEmails, isLoading: emailsLoading } = useAdminEmailLogs({
    page: 1,
    per_page: 5,
    status_filter: "failed",
  });

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-64 items-center justify-center text-red-400">
        <AlertCircle className="mr-2 h-5 w-5" />
        {t("failedToLoadStats")}
      </div>
    );
  }

  const unpaid = (overview?.invoices_open ?? 0) > 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("title")}</h1>
          <p className="mt-1 text-muted-foreground">
            {overview?.as_of
              ? t("platform.asOf", { date: overview.as_of })
              : t("description")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/admin/growth"
            className="flex items-center gap-2 rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground transition hover:bg-accent"
          >
            <TrendingUp className="h-4 w-4" />
            {t("platform.growthLink")}
          </Link>
          <button
            type="button"
            onClick={() => refresh.mutate(undefined)}
            disabled={refresh.isPending}
            data-testid="platform-stats-refresh"
            className="flex items-center gap-2 rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground transition hover:bg-accent disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${refresh.isPending ? "animate-spin" : ""}`} />
            {t("platform.refresh")}
          </button>
        </div>
      </div>

      {/* The figures below are a snapshot. If the job that writes it stopped,
          saying so beats quietly showing last week's numbers as today's. */}
      {overview?.is_stale && (
        <div
          data-testid="platform-stats-stale"
          className="flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
          <p className="text-foreground">{t("platform.stale")}</p>
        </div>
      )}

      {overview?.notes?.map((note) => (
        <div
          key={note}
          className="rounded-xl border border-border bg-muted p-4 text-sm text-muted-foreground"
        >
          {note}
        </div>
      ))}

      {/* Money */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {t("platform.moneyHeading")}
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label={t("platform.mrr")}
            kpi={overview?.mrr_cents}
            format="cents"
            hint={t("platform.mrrHint")}
          />
          <KpiCard
            label={t("platform.revenue")}
            kpi={overview?.revenue_cents}
            format="cents"
            hint={t("platform.revenueHint")}
          />
          <KpiCard
            label={t("platform.margin")}
            kpi={overview?.margin_cents}
            format="cents"
            hint={t("platform.marginHint", {
              cost: formatCents(overview?.base_cost_cents?.value ?? 0),
            })}
          />
          <KpiCard
            label={t("platform.payingWorkspaces")}
            kpi={overview?.paying_workspaces}
            hint={t("platform.trialing", {
              count: formatCount(overview?.trialing_workspaces?.value ?? 0),
            })}
          />
        </div>
      </section>

      {/* Reach */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {t("platform.reachHeading")}
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <KpiCard label={t("platform.workspaces")} kpi={overview?.workspaces_total} />
          <KpiCard
            label={t("platform.activeWorkspaces")}
            kpi={overview?.workspaces_active_30d}
            hint={t("platform.activeHint")}
          />
          <KpiCard label={t("platform.developers")} kpi={overview?.developers_total} />
          <KpiCard
            label={t("platform.seats")}
            kpi={overview?.billable_seats}
            hint={t("platform.seatsHint")}
          />
        </div>
      </section>

      {/* Splits */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <BreakdownList
          title={t("platform.revenueByTier")}
          entries={overview?.revenue_by_plan_tier ?? {}}
          empty={t("platform.noRevenue")}
        />
        <BreakdownList
          title={t("platform.revenueByModel")}
          entries={overview?.revenue_by_billing_model ?? {}}
          empty={t("platform.noRevenue")}
        />
        <BreakdownList
          title={t("platform.workspacesByTier")}
          entries={overview?.workspaces_by_plan_tier ?? {}}
          format="count"
          empty={t("platform.noWorkspaces")}
        />
      </div>

      {/* What needs chasing */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div
          className={`rounded-xl border p-5 ${
            (overview?.invoices_overdue ?? 0) > 0
              ? "border-red-500/40 bg-red-500/5"
              : "border-border bg-muted"
          }`}
        >
          <h3 className="text-sm font-medium text-foreground">
            {t("platform.unpaidHeading")}
          </h3>
          {unpaid ? (
            <div className="mt-2 space-y-1 text-sm">
              <p className="text-foreground">
                {t("platform.invoicesOpen", {
                  count: overview?.invoices_open ?? 0,
                  amount: formatCents(overview?.invoices_open_cents ?? 0),
                })}
              </p>
              {(overview?.invoices_overdue ?? 0) > 0 && (
                <p className="text-red-400">
                  {t("platform.invoicesOverdue", {
                    count: overview?.invoices_overdue ?? 0,
                    amount: formatCents(overview?.invoices_overdue_cents ?? 0),
                  })}
                </p>
              )}
              <Link
                href="/settings/admin-invoices"
                className="inline-block pt-1 text-blue-400 hover:underline"
              >
                {t("platform.viewInvoices")}
              </Link>
            </div>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">
              {t("platform.noUnpaid")}
            </p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-muted p-5">
          <h3 className="text-sm font-medium text-foreground">
            {t("platform.aiHeading")}
          </h3>
          <p className="mt-1 text-2xl font-bold text-foreground">
            {formatCents(overview?.llm_billed_cents?.value ?? 0)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("platform.aiHint")}
          </p>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {Object.entries(overview?.subscriptions_by_status ?? {}).map(
              ([status, count]) => (
                <span key={status} className="text-muted-foreground">
                  {status.replace(/_/g, " ")}:{" "}
                  <span className="text-foreground">{count}</span>
                </span>
              ),
            )}
          </div>
        </div>
      </div>

      {/* Operational shortcuts */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {[
          { href: "/admin/billing", icon: Building2, label: t("platform.billingLink") },
          { href: "/admin/workspaces", icon: Building2, label: t("quickLinks.workspaces") },
          { href: "/admin/users", icon: Users, label: t("quickLinks.users") },
          { href: "/admin/emails", icon: Mail, label: t("quickLinks.emailDelivery") },
        ].map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="group flex items-center justify-between rounded-xl border border-border bg-muted p-4 transition hover:border-blue-500/50"
          >
            <div className="flex items-center gap-3">
              <link.icon className="h-5 w-5 text-blue-400" />
              <span className="text-foreground">{link.label}</span>
            </div>
            <ChevronRight className="h-4 w-4 text-muted-foreground transition group-hover:text-foreground" />
          </Link>
        ))}
      </div>

      {/* Recent failed emails — the one operational signal worth the space. */}
      <div className="rounded-xl border border-border bg-muted">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
            <Bell className="h-4 w-4 text-muted-foreground" />
            {t("email.recentFailedEmails")}
          </h2>
          <Link href="/admin/emails?status=failed" className="text-sm text-blue-400 hover:underline">
            {t("email.viewAll")}
          </Link>
        </div>
        <div className="divide-y divide-border">
          {emailsLoading ? (
            <div className="flex justify-center p-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : recentEmails?.items?.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">
              <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-emerald-500" />
              <p>{t("email.noFailedEmails")}</p>
            </div>
          ) : (
            recentEmails?.items?.map((email) => (
              <div key={email.id} className="flex items-center justify-between px-5 py-4">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-foreground">{email.recipient_email}</p>
                  <p className="truncate text-sm text-muted-foreground">{email.subject}</p>
                </div>
                <div className="flex items-center gap-4">
                  <StatusBadge status={email.status} />
                  <span className="whitespace-nowrap text-sm text-muted-foreground">
                    {formatDistanceToNow(new Date(email.created_at), { addSuffix: true })}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
