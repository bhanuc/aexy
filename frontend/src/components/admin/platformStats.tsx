"use client";

import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { PlatformKpi } from "@/lib/api";

export function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

/**
 * One headline number with its movement since the comparison day.
 *
 * `previous` is null when no snapshot reaches that far back — a fresh
 * install, or a figure older than the table. That says "no comparison yet"
 * rather than drawing a 0% change, which would read as "flat" when the truth
 * is "unknown".
 */
export function KpiCard({
  label,
  kpi,
  format = "count",
  hint,
  /** Down is good for cost. */
  invertTrend = false,
}: {
  label: string;
  kpi?: PlatformKpi;
  format?: "count" | "cents";
  hint?: string;
  invertTrend?: boolean;
}) {
  const t = useTranslations("admin");
  const value = kpi?.value ?? 0;
  const render = format === "cents" ? formatCents : formatCount;
  const delta = kpi?.delta ?? null;
  const hasComparison = kpi?.previous !== null && kpi?.previous !== undefined;

  const flat = delta === null || Math.abs(delta) < 0.5;
  const up = (delta ?? 0) > 0;
  const good = invertTrend ? !up : up;
  const Icon = flat ? ArrowRight : up ? ArrowUpRight : ArrowDownRight;

  return (
    <div className="rounded-xl border border-border bg-muted p-5">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-bold text-foreground">{render(value)}</p>
      {hasComparison ? (
        <p
          className={cn(
            "mt-1 flex items-center gap-1 text-sm",
            flat
              ? "text-muted-foreground"
              : good
                ? "text-emerald-500"
                : "text-red-400",
          )}
        >
          <Icon className="h-3 w-3 shrink-0" />
          <span>
            {flat
              ? t("platform.noChange")
              : `${up ? "+" : ""}${render(delta ?? 0)}`}
          </span>
          {kpi?.delta_pct !== null && kpi?.delta_pct !== undefined && !flat && (
            <span className="text-muted-foreground">
              ({kpi.delta_pct > 0 ? "+" : ""}
              {kpi.delta_pct.toFixed(1)}%)
            </span>
          )}
        </p>
      ) : (
        <p className="mt-1 text-sm text-muted-foreground">
          {t("platform.noComparison")}
        </p>
      )}
      {hint && <p className="mt-2 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** A labelled money split — revenue by tier, by billing model. */
export function BreakdownList({
  title,
  entries,
  format = "cents",
  empty,
}: {
  title: string;
  entries: Record<string, number>;
  format?: "count" | "cents";
  empty: string;
}) {
  const render = format === "cents" ? formatCents : formatCount;
  const rows = Object.entries(entries).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((sum, [, value]) => sum + value, 0);

  return (
    <div className="rounded-xl border border-border bg-muted p-5">
      <h3 className="text-sm font-medium text-foreground">{title}</h3>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {rows.map(([key, value]) => (
            <li key={key} className="space-y-1">
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="truncate capitalize text-muted-foreground">
                  {key.replace(/_/g, " ")}
                </span>
                <span className="shrink-0 font-medium text-foreground">
                  {render(value)}
                </span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-accent">
                <div
                  className="h-full bg-blue-500"
                  style={{ width: total > 0 ? `${(value / total) * 100}%` : "0%" }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
