"use client";

import { use } from "react";
import Link from "next/link";
import { AlertCircle, ArrowLeft, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { formatDistanceToNow } from "date-fns";

import { useAdminWorkspaceDetail } from "@/hooks/useAdmin";
import { formatCents, formatCount } from "@/components/admin/platformStats";

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{value ?? "—"}</dd>
    </div>
  );
}

export default function AdminWorkspaceDetailPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  const t = useTranslations("admin");
  const { data, isLoading, error } = useAdminWorkspaceDetail(workspaceId);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex h-64 items-center justify-center text-red-400">
        <AlertCircle className="mr-2 h-5 w-5" />
        {t("workspaceDetail.failed")}
      </div>
    );
  }

  const modules = Object.entries(data.module_usage).sort((a, b) => b[1] - a[1]);
  const margin = data.llm_billed_cents_this_period - data.llm_base_cost_cents_this_period;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <Link
        href="/admin/workspaces"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        {t("workspaceDetail.back")}
      </Link>

      <div>
        <h1 className="text-2xl font-bold text-foreground">{data.name}</h1>
        <p className="mt-1 text-muted-foreground">
          {data.slug}
          {!data.is_active && ` · ${t("workspaceDetail.inactive")}`}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-border bg-muted p-5">
          <h2 className="text-sm font-medium text-foreground">
            {t("workspaceDetail.account")}
          </h2>
          <dl className="mt-4 grid grid-cols-2 gap-4">
            <Field label={t("workspaceDetail.owner")} value={data.owner_name} />
            <Field label={t("workspaceDetail.ownerEmail")} value={data.owner_email} />
            <Field
              label={t("workspaceDetail.plan")}
              value={
                <>
                  {data.plan_name ?? t("workspaceDetail.noPlan")}
                  {data.has_plan_override && (
                    <span className="ml-2 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-500">
                      {t("workspaceDetail.overridden")}
                    </span>
                  )}
                </>
              }
            />
            <Field label={t("workspaceDetail.billingModel")} value={data.billing_model} />
            <Field
              label={t("workspaceDetail.subscription")}
              value={data.subscription_status ?? t("workspaceDetail.noSubscription")}
            />
            <Field
              label={t("workspaceDetail.renews")}
              value={
                data.current_period_end
                  ? new Date(data.current_period_end).toLocaleDateString()
                  : null
              }
            />
            <Field
              label={t("workspaceDetail.members")}
              value={`${formatCount(data.member_count)} (${formatCount(data.billable_seats)} ${t("workspaceDetail.billable")})`}
            />
            <Field
              label={t("workspaceDetail.created")}
              value={new Date(data.created_at).toLocaleDateString()}
            />
          </dl>
          <div className="mt-4 flex flex-wrap gap-3 text-sm">
            <Link href="/admin/billing" className="text-blue-400 hover:underline">
              {t("workspaceDetail.billingLink")}
            </Link>
            <Link href="/settings/plan-overrides" className="text-blue-400 hover:underline">
              {t("workspaceDetail.overrideLink")}
            </Link>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-muted p-5">
          <h2 className="text-sm font-medium text-foreground">
            {t("workspaceDetail.aiThisPeriod")}
          </h2>
          <p className="mt-1 text-2xl font-bold text-foreground">
            {formatCents(data.llm_billed_cents_this_period)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("workspaceDetail.aiBreakdown", {
              cost: formatCents(data.llm_base_cost_cents_this_period),
              margin: formatCents(margin),
            })}
          </p>
          <dl className="mt-4 grid grid-cols-2 gap-4">
            <Field
              label={t("workspaceDetail.requests")}
              value={formatCount(data.llm_requests_this_period)}
            />
            <Field
              label={t("workspaceDetail.tokens")}
              value={formatCount(data.llm_tokens_this_period)}
            />
            <Field
              label={t("workspaceDetail.lastActivity")}
              value={
                data.last_activity_at
                  ? formatDistanceToNow(new Date(data.last_activity_at), {
                      addSuffix: true,
                    })
                  : t("workspaceDetail.noActivity")
              }
            />
          </dl>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-muted p-5">
        <h2 className="text-sm font-medium text-foreground">
          {t("workspaceDetail.modules")}
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {t("workspaceDetail.modulesHint")}
        </p>
        {modules.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            {t("workspaceDetail.noModules")}
          </p>
        ) : (
          <div className="mt-4 flex flex-wrap gap-2">
            {modules.map(([module, count]) => (
              <span
                key={module}
                data-testid="workspace-module"
                className="rounded-full border border-border bg-background/50 px-3 py-1 text-xs text-foreground"
              >
                <span className="capitalize">{module.replace(/_/g, " ")}</span>
                <span className="ml-1.5 tabular-nums text-muted-foreground">
                  {formatCount(count)}
                </span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
