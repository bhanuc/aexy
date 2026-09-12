"use client";

import { useMemo, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { useModuleAdoption } from "@/hooks/useAdmin";
import { formatCount } from "@/components/admin/platformStats";
import { cn } from "@/lib/utils";
import type { ModuleAdoptionPoint } from "@/lib/api";

const RANGES = [30, 90, 180];

/** A module nobody has touched should not look the same as one at full reach. */
function shareTone(share: number) {
  if (share >= 0.5) return "bg-emerald-500";
  if (share >= 0.2) return "bg-blue-500";
  if (share > 0) return "bg-amber-500";
  return "bg-muted-foreground/20";
}

export default function ModuleAdoptionPage() {
  const t = useTranslations("admin");
  const [days, setDays] = useState(90);
  const { data, isLoading, error } = useModuleAdoption(days);

  // The matrix is "module × day", newest day first, so the current picture is
  // the left-hand column and the trend reads across.
  const { modules, dayColumns, latest } = useMemo(() => {
    const points = data?.points ?? [];
    const byDay = new Map<string, Map<string, ModuleAdoptionPoint>>();
    for (const point of points) {
      const day = String(point.day);
      if (!byDay.has(day)) byDay.set(day, new Map());
      byDay.get(day)!.set(point.module, point);
    }
    const dayColumns = [...byDay.keys()].sort().reverse().slice(0, 12);
    const modules = [...new Set(points.map((p) => p.module))].sort((a, b) => {
      const newest = dayColumns[0];
      const av = byDay.get(newest)?.get(a)?.workspaces_active ?? 0;
      const bv = byDay.get(newest)?.get(b)?.workspaces_active ?? 0;
      return bv - av || a.localeCompare(b);
    });
    return { modules, dayColumns, latest: byDay.get(dayColumns[0]) };
  }, [data]);

  // The denominator is workspaces that did *anything* in the same window each
  // row counts over, not every workspace that exists — dividing by the second
  // understates every module on a platform with dormant tenants.
  const total = data?.active_workspaces ?? 0;
  const allWorkspaces = data?.total_workspaces ?? 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("adoption.title")}</h1>
          <p className="mt-1 text-muted-foreground">
            {t("adoption.description", { days: data?.window_days ?? 30 })}
          </p>
          {total > 0 && (
            <p className="mt-1 text-sm text-muted-foreground" data-testid="adoption-denominator">
              {t("adoption.denominator", { active: total, total: allWorkspaces })}
            </p>
          )}
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
          {t("adoption.failed")}
        </div>
      ) : modules.length === 0 ? (
        <div
          data-testid="adoption-empty"
          className="rounded-xl border border-border bg-muted p-8 text-center"
        >
          <p className="text-foreground">{t("adoption.empty")}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t("adoption.emptyHint")}</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-muted">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="px-4 py-3 font-medium">{t("adoption.module")}</th>
                <th className="px-4 py-3 font-medium">{t("adoption.reach")}</th>
                <th className="px-4 py-3 font-medium">{t("adoption.volume")}</th>
                {dayColumns.map((day) => (
                  <th key={day} className="px-2 py-3 text-center font-normal">
                    {day.slice(5)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {modules.map((module) => {
                const current = latest?.get(module);
                const active = current?.workspaces_active ?? 0;
                const share = total > 0 ? active / total : 0;
                return (
                  <tr
                    key={module}
                    data-testid="adoption-row"
                    className="border-b border-border/60 last:border-0"
                  >
                    <td className="px-4 py-3 font-medium capitalize text-foreground">
                      {module.replace(/_/g, " ")}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="w-16 shrink-0 tabular-nums text-foreground">
                          {active} / {total}
                        </span>
                        <span className="h-1.5 w-24 overflow-hidden rounded-full bg-accent">
                          <span
                            className={cn("block h-full", shareTone(share))}
                            style={{ width: `${Math.round(share * 100)}%` }}
                          />
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 tabular-nums text-muted-foreground">
                      {formatCount(current?.events ?? 0)}
                    </td>
                    {dayColumns.map((day) => {
                      const point = data?.points.find(
                        (p) => String(p.day) === day && p.module === module,
                      );
                      const dayShare =
                        total > 0 ? (point?.workspaces_active ?? 0) / total : 0;
                      return (
                        <td key={day} className="px-2 py-3 text-center">
                          <span
                            title={`${point?.workspaces_active ?? 0} / ${total}`}
                            className={cn(
                              "mx-auto block h-4 w-4 rounded",
                              shareTone(dayShare),
                            )}
                          />
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* A module with no signal must not read as a module nobody uses. */}
      {(data?.not_measured?.length ?? 0) > 0 && (
        <div className="rounded-xl border border-border bg-muted p-5">
          <h2 className="text-sm font-medium text-foreground">
            {t("adoption.notMeasured")}
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("adoption.notMeasuredHint")}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {data?.not_measured.map((module) => (
              <span
                key={module}
                className="rounded-full border border-border px-2.5 py-0.5 text-xs capitalize text-muted-foreground"
              >
                {module.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
