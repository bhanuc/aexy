"use client";

import { useState, useEffect } from "react";
import { Calendar } from "lucide-react";
import { publicProjectApi, PublicSprintItem } from "@/lib/api";
import { SPRINT_STATUS_COLORS } from "./constants";
import { LoadingSpinner, EmptyState } from "./shared";

interface SprintsTabProps {
  publicSlug: string;
}

export function SprintsTab({ publicSlug }: SprintsTabProps) {
  const [sprints, setSprints] = useState<PublicSprintItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getSprints(publicSlug).then(setSprints).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (sprints.length === 0) return <EmptyState message="No sprints" />;

  return (
    <div className="space-y-3">
      {sprints.map((sprint) => {
        const completionRate = sprint.tasks_count > 0
          ? Math.round((sprint.completed_count / sprint.tasks_count) * 100)
          : 0;

        return (
          <div key={sprint.id} className="bg-slate-800 rounded-lg p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <div className={`w-3 h-3 rounded-full ${SPRINT_STATUS_COLORS[sprint.status] || SPRINT_STATUS_COLORS.planning}`} />
                  <h3 className="text-white font-medium">{sprint.name}</h3>
                </div>
                {sprint.goal && (
                  <p className="text-slate-400 text-sm mt-1 line-clamp-2">{sprint.goal}</p>
                )}
                <div className="mt-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-slate-400">
                      {sprint.completed_count}/{sprint.tasks_count} tasks
                    </span>
                    <span className="text-slate-300">{completionRate}%</span>
                  </div>
                  <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary-500 rounded-full transition-all"
                      style={{ width: `${completionRate}%` }}
                    />
                  </div>
                </div>
                <div className="flex items-center gap-3 mt-2 flex-wrap">
                  <span className="text-xs text-slate-500 capitalize">{sprint.status}</span>
                  <span className="flex items-center gap-1 text-xs text-slate-500">
                    <Calendar className="h-3 w-3" />
                    {new Date(sprint.start_date).toLocaleDateString()} - {new Date(sprint.end_date).toLocaleDateString()}
                  </span>
                  <span className="text-xs text-slate-500">{sprint.total_points} pts</span>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
