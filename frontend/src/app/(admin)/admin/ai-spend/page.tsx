"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertCircle, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useAiSpend } from "@/hooks/useAdmin";
import { formatCents, formatCount } from "@/components/admin/platformStats";
import { cn } from "@/lib/utils";

const RANGES = [7, 30, 90];

const TOOLTIP_STYLE = {
  backgroundColor: "hsl(var(--popover))",
  border: "1px solid hsl(var(--border))",
  borderRadius: 8,
  fontSize: 12,
  color: "hsl(var(--popover-foreground))",
};

function money(value: unknown) {
  return value === null || value === undefined ? "—" : formatCents(Number(value));
}

export default function AiSpendPage() {
  const t = useTranslations("admin");
  const [days, setDays] = useState(30);
  const { data, isLoading, error } = useAiSpend(days);

  const billed = data?.by_day.reduce((sum, d) => sum + d.billed_cents, 0) ?? 0;
  const cost = data?.by_day.reduce((sum, d) => sum + d.base_cost_cents, 0) ?? 0;
  const tokens = data?.by_day.reduce((sum, d) => sum + d.tokens, 0) ?? 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("aiSpend.title")}</h1>
          <p className="mt-1 text-muted-foreground">{t("aiSpend.description")}</p>
        </div>
        <div className="flex gap-1 rounded-lg border border-border bg-muted p-1">
          {RANGES.map((range) => (
            <button
              key={range}
              type="button"
              onClick={() => setDays(range)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm transition",
                days === range
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
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
          {t("aiSpend.failed")}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-border bg-muted p-5">
              <p className="text-sm text-muted-foreground">{t("aiSpend.billed")}</p>
              <p className="mt-1 text-2xl font-bold text-foreground">
                {formatCents(billed)}
              </p>
            </div>
            <div className="rounded-xl border border-border bg-muted p-5">
              <p className="text-sm text-muted-foreground">{t("aiSpend.providerCost")}</p>
              <p className="mt-1 text-2xl font-bold text-foreground">
                {formatCents(cost)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("aiSpend.marginLine", { amount: formatCents(billed - cost) })}
              </p>
            </div>
            <div className="rounded-xl border border-border bg-muted p-5">
              <p className="text-sm text-muted-foreground">{t("aiSpend.tokens")}</p>
              <p className="mt-1 text-2xl font-bold text-foreground">
                {formatCount(tokens)}
              </p>
            </div>
          </div>

          {data?.by_day.length ? (
            <div className="rounded-xl border border-border bg-muted p-5">
              <h2 className="text-sm font-medium text-foreground">
                {t("aiSpend.perDay")}
              </h2>
              <div className="mt-4 h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={data.by_day}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis dataKey="day" stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis tickFormatter={(v) => formatCents(Number(v))} stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} formatter={money} />
                    <Area type="monotone" dataKey="billed_cents" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.2} name={t("aiSpend.billed")} />
                    <Area type="monotone" dataKey="base_cost_cents" stroke="#ef4444" fill="#ef4444" fillOpacity={0.15} name={t("aiSpend.providerCost")} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : (
            <div
              data-testid="ai-spend-empty"
              className="rounded-xl border border-border bg-muted p-8 text-center"
            >
              <p className="text-foreground">{t("aiSpend.empty")}</p>
              <p className="mt-1 text-sm text-muted-foreground">{t("aiSpend.emptyHint")}</p>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-muted">
              <h2 className="border-b border-border px-5 py-4 text-sm font-medium text-foreground">
                {t("aiSpend.topWorkspaces")}
              </h2>
              {data?.top_workspaces.length ? (
                <ul className="divide-y divide-border">
                  {data.top_workspaces.map((row) => (
                    <li key={row.workspace_id} className="flex items-center justify-between gap-3 px-5 py-3">
                      <Link
                        href={`/admin/workspaces/${row.workspace_id}`}
                        className="truncate text-sm text-blue-400 hover:underline"
                      >
                        {row.workspace_name}
                      </Link>
                      <span className="shrink-0 text-sm tabular-nums text-foreground">
                        {formatCents(row.billed_cents)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="px-5 py-6 text-sm text-muted-foreground">
                  {t("aiSpend.noWorkspaces")}
                </p>
              )}
            </div>

            <div className="rounded-xl border border-border bg-muted">
              <h2 className="border-b border-border px-5 py-4 text-sm font-medium text-foreground">
                {t("aiSpend.byFeature")}
              </h2>
              {data?.by_feature.length ? (
                <ul className="divide-y divide-border">
                  {data.by_feature.map((row) => (
                    <li key={row.feature} className="flex items-center justify-between gap-3 px-5 py-3">
                      <span className="truncate text-sm capitalize text-foreground">
                        {row.feature.replace(/_/g, " ")}
                      </span>
                      <span className="shrink-0 text-sm tabular-nums text-muted-foreground">
                        {formatCents(row.billed_cents)} · {formatCount(row.requests)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="px-5 py-6 text-sm text-muted-foreground">
                  {t("aiSpend.noFeatures")}
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
