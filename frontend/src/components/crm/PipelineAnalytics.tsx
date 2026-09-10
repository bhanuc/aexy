"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { TrendingUp, DollarSign, Trophy, Layers } from "lucide-react";
import { CRMPipeline } from "@/lib/api";
import { usePipelineAnalytics } from "@/hooks/usePipelines";

interface PipelineAnalyticsProps {
  workspaceId: string;
  pipeline: CRMPipeline;
}

const money = (n: number) =>
  "$" + Math.round(n || 0).toLocaleString();

const duration = (seconds: number) => {
  if (!seconds || seconds <= 0) return "—";
  const days = seconds / 86400;
  if (days >= 1) return `${days.toFixed(1)}d`;
  const hours = seconds / 3600;
  if (hours >= 1) return `${hours.toFixed(1)}h`;
  return `${Math.round(seconds / 60)}m`;
};

function Kpi({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-border/50 bg-muted/20 p-4">
      <div className="flex items-center gap-2 text-muted-foreground text-xs uppercase tracking-wide">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-foreground">{value}</div>
      {hint && <div className="text-xs text-muted-foreground mt-1">{hint}</div>}
    </div>
  );
}

export function PipelineAnalytics({ workspaceId, pipeline }: PipelineAnalyticsProps) {
  const { summary, forecast, conversion, velocity } = usePipelineAnalytics(
    workspaceId,
    pipeline.id
  );

  const stageColor = useMemo(() => {
    const m: Record<string, string> = {};
    (pipeline.stages || []).forEach((s) => {
      m[s.value_key] = s.color || "#6B7280";
    });
    return m;
  }, [pipeline.stages]);

  const barData = (summary.data?.stages || []).map((s) => ({
    name: s.name,
    key: s.stage_key,
    count: s.count,
    value: s.total_value,
    weighted: Math.round(s.weighted_value),
  }));

  const velocityMap: Record<string, number> = velocity.data?.avg_seconds_in_stage || {};

  const isLoading = summary.isLoading || forecast.isLoading;

  return (
    <div className="space-y-6">
      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi
          icon={<TrendingUp className="h-4 w-4" />}
          label="Weighted forecast"
          value={money(forecast.data?.weighted_forecast || 0)}
          hint="Open value × win probability"
        />
        <Kpi
          icon={<DollarSign className="h-4 w-4" />}
          label="Open value"
          value={money(forecast.data?.open_value || 0)}
          hint={`${forecast.data?.open_count ?? 0} open records`}
        />
        <Kpi
          icon={<Trophy className="h-4 w-4" />}
          label="Won value"
          value={money(forecast.data?.won_value || 0)}
        />
        <Kpi
          icon={<Layers className="h-4 w-4" />}
          label="Stages"
          value={String((pipeline.stages || []).length)}
          hint={pipeline.name}
        />
      </div>

      {/* Value by stage */}
      <div className="rounded-xl border border-border/50 bg-muted/20 p-4">
        <h3 className="text-sm font-medium text-foreground mb-4">Value by stage</h3>
        {isLoading ? (
          <div className="h-64 animate-pulse bg-accent/40 rounded-lg" />
        ) : barData.length === 0 ? (
          <div className="h-64 flex items-center justify-center text-muted-foreground text-sm">
            No records in this pipeline yet
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={barData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} />
              <YAxis tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} />
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--background))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={((v: number) => [money(v), "Value"]) as never}
              />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {barData.map((d) => (
                  <Cell key={d.key} fill={stageColor[d.key] || "#6B7280"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Conversion funnel */}
        <div className="rounded-xl border border-border/50 bg-muted/20 p-4">
          <h3 className="text-sm font-medium text-foreground mb-4">
            Conversion (last {conversion.data?.window_days ?? 90} days)
          </h3>
          <div className="space-y-3">
            {(conversion.data?.stages || []).map((s: any) => {
              const maxEntered =
                Math.max(1, ...(conversion.data?.stages || []).map((x: any) => x.entered || 0));
              const pct = Math.round(((s.entered || 0) / maxEntered) * 100);
              return (
                <div key={s.stage_key}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-foreground">{s.name}</span>
                    <span className="text-muted-foreground">
                      {s.entered} entered
                      {s.conversion_to_next != null && (
                        <span className="ml-2 text-green-400">
                          {Math.round(s.conversion_to_next * 100)}% →
                        </span>
                      )}
                    </span>
                  </div>
                  <div className="h-2 bg-accent/40 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${pct}%`, backgroundColor: stageColor[s.stage_key] || "#6B7280" }}
                    />
                  </div>
                </div>
              );
            })}
            {(conversion.data?.stages || []).every((s: any) => !s.entered) && (
              <p className="text-sm text-muted-foreground">No stage transitions recorded yet.</p>
            )}
          </div>
        </div>

        {/* Stage velocity */}
        <div className="rounded-xl border border-border/50 bg-muted/20 p-4">
          <h3 className="text-sm font-medium text-foreground mb-4">Average time in stage</h3>
          <div className="space-y-2">
            {(pipeline.stages || []).map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between text-sm border-b border-border/30 pb-2 last:border-0"
              >
                <span className="flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: s.color || "#6B7280" }}
                  />
                  <span className="text-foreground">{s.name}</span>
                </span>
                <span className="text-muted-foreground">{duration(velocityMap[s.value_key])}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
