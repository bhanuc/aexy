"use client";

import { useState, useEffect } from "react";
import { publicProjectApi, PublicGoalItem } from "@/lib/api";
import { LoadingSpinner, EmptyState } from "./shared";

interface GoalsTabProps {
  publicSlug: string;
}

export function GoalsTab({ publicSlug }: GoalsTabProps) {
  const [goals, setGoals] = useState<PublicGoalItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    publicProjectApi.getGoals(publicSlug).then(setGoals).finally(() => setIsLoading(false));
  }, [publicSlug]);

  if (isLoading) return <LoadingSpinner />;
  if (goals.length === 0) return <EmptyState message="No goals defined" />;

  return (
    <div className="space-y-3">
      {goals.map((goal) => (
        <div key={goal.id} className="bg-slate-800 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <span className="text-xs font-mono text-slate-500 bg-slate-700 px-2 py-1 rounded">{goal.key}</span>
            <div className="flex-1 min-w-0">
              <h3 className="text-white font-medium">{goal.title}</h3>
              {goal.description && (
                <p className="text-slate-400 text-sm mt-1 line-clamp-2">{goal.description}</p>
              )}
              <div className="mt-3">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-slate-400">Progress</span>
                  <span className="text-slate-300">{Math.round(goal.progress_percentage)}%</span>
                </div>
                <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary-500 rounded-full transition-all"
                    style={{ width: `${goal.progress_percentage}%` }}
                  />
                </div>
              </div>
              <div className="flex items-center gap-2 mt-2">
                <span className="text-xs text-slate-500">{goal.goal_type}</span>
                <span className="text-xs text-slate-500">{goal.status}</span>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
