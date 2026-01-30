"use client";

import { Users, Layers, Calendar } from "lucide-react";
import { PublicProject } from "@/lib/api";

interface OverviewTabProps {
  project: PublicProject;
}

export function OverviewTab({ project }: OverviewTabProps) {
  return (
    <div className="space-y-6">
      {project.description && (
        <div className="bg-slate-800 rounded-xl p-6">
          <h2 className="text-lg font-medium text-white mb-3">About</h2>
          <p className="text-slate-300 whitespace-pre-wrap">{project.description}</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-slate-800 rounded-xl p-6">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-blue-500/10 rounded-lg">
              <Users className="h-5 w-5 text-blue-400" />
            </div>
            <span className="text-slate-400 text-sm">Members</span>
          </div>
          <p className="text-2xl font-bold text-white">{project.member_count}</p>
        </div>

        <div className="bg-slate-800 rounded-xl p-6">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-purple-500/10 rounded-lg">
              <Layers className="h-5 w-5 text-purple-400" />
            </div>
            <span className="text-slate-400 text-sm">Teams</span>
          </div>
          <p className="text-2xl font-bold text-white">{project.team_count}</p>
        </div>

        <div className="bg-slate-800 rounded-xl p-6">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-green-500/10 rounded-lg">
              <Calendar className="h-5 w-5 text-green-400" />
            </div>
            <span className="text-slate-400 text-sm">Created</span>
          </div>
          <p className="text-2xl font-bold text-white">
            {new Date(project.created_at).toLocaleDateString("en-US", {
              month: "short",
              year: "numeric",
            })}
          </p>
        </div>
      </div>
    </div>
  );
}
