"use client";

import { useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { usePlatformStatsSeries } from "@/hooks/useAdmin";
import { formatCents, formatCount } from "@/components/admin/platformStats";
import type { PlatformStatsPoint } from "@/lib/api";

const RANGES = [30, 90, 180, 365];

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border bg-muted p-5">
      <h2 className="text-sm font-medium text-foreground">{title}</h2>
      {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      <div className="mt-4 h-64">{children}</div>
    </div>
  );
}

const axis = {
  stroke: "hsl(var(--muted-foreground))",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
};

const TOOLTIP_STYLE = {
  backgroundColor: "hsl(var(--popover))",
  border: "1px solid hsl(var(--border))",
  borderRadius: 8,
  fontSize: 12,
  color: "hsl(var(--popover-foreground))",
};

/** Recharts hands the formatter `unknown`; a gap-day value is undefined. */
function money(value: unknown) {
  return value === null || value === undefined ? "—" : formatCents(Number(value));
}

function count(value: unknown) {
  return value === null || value === undefined ? "—" : formatCount(Number(value));
}

export default function PlatformGrowthPage() {
  const t = useTranslations("admin");
  const [days, setDays] = useState(90);
  const { data, isLoading, error } = usePlatformStatsSeries(days);

  const points = data?.points ?? [];
  // A backfilled day could not recover subscription or revenue figures, so
  // those series are undefined there. Recharts leaves a gap rather than
  // drawing a plunge to zero that never happened.
  const billingSeries = points.map((p: PlatformStatsPoint) => ({
    ...p,
    mrr_cents: p.is_partial ? undefined : p.mrr_cents,
    revenue_cents: p.is_partial ? undefined : p.revenue_cents,
    margin_cents: p.is_partial ? undefined : p.margin_cents,
    paying_workspaces: p.is_partial ? undefined : p.paying_workspaces,
  }));

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("growth.title")}</h1>
          <p className="mt-1 text-muted-foreground">{t("growth.description")}</p>
        </div>
        <div className="flex gap-1 rounded-lg border border-border bg-muted p-1">
          {RANGES.map((range) => (
            <button
              key={range}
              type="button"
              onClick={() => setDays(range)}
              className={`rounded-md px-3 py-1.5 text-sm transition ${
                days === range
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t("growth.days", { count: range })}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
        </div>
      ) : error ? (
        <div className="flex h-64 items-center justify-center text-red-400">
          <AlertCircle className="mr-2 h-5 w-5" />
          {t("growth.failed")}
        </div>
      ) : points.length < 2 ? (
        // One snapshot is a dot, not a trend. Saying so is more use than an
        // empty chart frame.
        <div
          data-testid="platform-growth-empty"
          className="rounded-xl border border-border bg-muted p-8 text-center"
        >
          <p className="text-foreground">{t("growth.notEnoughData")}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("growth.notEnoughDataHint")}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title={t("growth.signups")} subtitle={t("growth.signupsHint")}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={points}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis dataKey="day" {...axis} />
                <YAxis allowDecimals={false} {...axis} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={count} />
                <Bar dataKey="workspaces_created" fill="#3b82f6" name={t("growth.newWorkspaces")} radius={[2, 2, 0, 0]} />
                <Bar dataKey="developers_created" fill="#8b5cf6" name={t("growth.newDevelopers")} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Panel>

          <Panel title={t("growth.totals")} subtitle={t("growth.totalsHint")}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis dataKey="day" {...axis} />
                <YAxis allowDecimals={false} {...axis} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={count} />
                <Area type="monotone" dataKey="workspaces_total" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.15} name={t("growth.workspaces")} />
                <Area type="monotone" dataKey="workspaces_active_30d" stroke="#10b981" fill="#10b981" fillOpacity={0.15} name={t("growth.active")} />
              </AreaChart>
            </ResponsiveContainer>
          </Panel>

          <Panel title={t("growth.mrr")} subtitle={t("growth.mrrHint")}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={billingSeries}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis dataKey="day" {...axis} />
                <YAxis tickFormatter={(v) => formatCents(Number(v))} {...axis} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={money} />
                <Line type="monotone" dataKey="mrr_cents" stroke="#10b981" strokeWidth={2} dot={false} connectNulls={false} name={t("growth.mrrSeries")} />
                <Line type="monotone" dataKey="revenue_cents" stroke="#3b82f6" strokeWidth={2} dot={false} connectNulls={false} name={t("growth.revenueSeries")} />
                <Line type="monotone" dataKey="margin_cents" stroke="#f59e0b" strokeWidth={2} dot={false} connectNulls={false} name={t("growth.marginSeries")} />
              </LineChart>
            </ResponsiveContainer>
          </Panel>

          <Panel title={t("growth.aiCost")} subtitle={t("growth.aiCostHint")}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis dataKey="day" {...axis} />
                <YAxis tickFormatter={(v) => formatCents(Number(v))} {...axis} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={money} />
                <Area type="monotone" dataKey="llm_billed_cents" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.2} name={t("growth.aiBilled")} />
                <Area type="monotone" dataKey="llm_base_cost_cents" stroke="#ef4444" fill="#ef4444" fillOpacity={0.15} name={t("growth.aiCostSeries")} />
              </AreaChart>
            </ResponsiveContainer>
          </Panel>

          <Panel title={t("growth.customers")} subtitle={t("growth.customersHint")}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={billingSeries}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis dataKey="day" {...axis} />
                <YAxis allowDecimals={false} {...axis} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={count} />
                <Line type="monotone" dataKey="paying_workspaces" stroke="#10b981" strokeWidth={2} dot={false} connectNulls={false} name={t("growth.paying")} />
                <Line type="monotone" dataKey="billable_seats" stroke="#3b82f6" strokeWidth={2} dot={false} name={t("growth.seats")} />
              </LineChart>
            </ResponsiveContainer>
          </Panel>

          <Panel title={t("growth.churn")} subtitle={t("growth.churnHint")}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={points}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis dataKey="day" {...axis} />
                <YAxis allowDecimals={false} {...axis} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={count} />
                <Bar dataKey="subscriptions_canceled" fill="#ef4444" name={t("growth.canceled")} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Panel>
        </div>
      )}
    </div>
  );
}
