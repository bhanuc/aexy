"use client";

import { useState, useEffect } from "react";
import { publicProjectApi, PublicRoadmapItem } from "@/lib/api";
import { SPRINT_STATUS_COLORS } from "./constants";
import { LoadingSpinner, EmptyState } from "./shared";

interface RoadmapTabProps {
  publicSlug: string;
}

export function RoadmapTab({ publicSlug }: RoadmapTabProps) {
  const [sprints, setSprints] = useState<PublicRoadmapItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getRoadmap(publicSlug).then(setSprints).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (sprints.length === 0) return <EmptyState message="No sprints in the roadmap" />;

  // Calculate timeline range
  const now = new Date();
  const allDates = sprints.flatMap(s => [new Date(s.start_date), new Date(s.end_date)]);
  const minDate = new Date(Math.min(...allDates.map(d => d.getTime()), now.getTime()));
  const maxDate = new Date(Math.max(...allDates.map(d => d.getTime()), now.getTime()));

  // Add some padding
  minDate.setDate(minDate.getDate() - 7);
  maxDate.setDate(maxDate.getDate() + 14);

  const totalDays = (maxDate.getTime() - minDate.getTime()) / (1000 * 60 * 60 * 24);
  const todayOffset = ((now.getTime() - minDate.getTime()) / (1000 * 60 * 60 * 24) / totalDays) * 100;

  return (
    <div className="space-y-4">
      {/* Timeline header */}
      <div className="bg-slate-800 rounded-lg p-4">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
          <span>{minDate.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
          <span>Today</span>
          <span>{maxDate.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
        </div>
        <div className="relative h-2 bg-slate-700 rounded-full">
          {/* Today marker */}
          <div
            className="absolute top-0 w-0.5 h-4 -mt-1 bg-primary-500 z-10"
            style={{ left: `${todayOffset}%` }}
          />
        </div>
      </div>

      {/* Sprint bars */}
      <div className="space-y-3">
        {sprints.map((sprint) => {
          const startDate = new Date(sprint.start_date);
          const endDate = new Date(sprint.end_date);
          const startOffset = ((startDate.getTime() - minDate.getTime()) / (1000 * 60 * 60 * 24) / totalDays) * 100;
          const width = ((endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24) / totalDays) * 100;
          const completionRate = sprint.tasks_count > 0
            ? Math.round((sprint.completed_count / sprint.tasks_count) * 100)
            : 0;

          return (
            <div key={sprint.id} className="bg-slate-800 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <div className={`w-3 h-3 rounded-full ${SPRINT_STATUS_COLORS[sprint.status] || SPRINT_STATUS_COLORS.planning}`} />
                  <h3 className="text-white font-medium">{sprint.name}</h3>
                  <span className="text-xs text-slate-500 capitalize">{sprint.status}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-400">
                  <span>{sprint.tasks_count} tasks</span>
                  <span>{sprint.total_points} pts</span>
                </div>
              </div>

              {sprint.goal && (
                <p className="text-slate-400 text-sm mb-3">{sprint.goal}</p>
              )}

              {/* Timeline bar */}
              <div className="relative h-8 bg-slate-700/50 rounded-lg overflow-hidden">
                <div
                  className={`absolute h-full rounded-lg ${SPRINT_STATUS_COLORS[sprint.status] || SPRINT_STATUS_COLORS.planning} ${sprint.status === "completed" ? "opacity-60" : ""}`}
                  style={{ left: `${Math.max(0, startOffset)}%`, width: `${Math.min(100 - startOffset, width)}%` }}
                >
                  {/* Progress inside */}
                  <div
                    className="absolute inset-y-0 left-0 bg-white/20 rounded-l-lg"
                    style={{ width: `${completionRate}%` }}
                  />
                  <div className="relative h-full flex items-center px-2">
                    <span className="text-xs text-white font-medium truncate">{completionRate}% complete</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between mt-2 text-xs text-slate-500">
                <span>{startDate.toLocaleDateString()}</span>
                <span>{endDate.toLocaleDateString()}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-4 pt-4">
        {Object.entries(SPRINT_STATUS_COLORS).map(([status, color]) => (
          <div key={status} className="flex items-center gap-1.5">
            <div className={`w-3 h-3 rounded ${color}`} />
            <span className="text-xs text-slate-400 capitalize">{status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
