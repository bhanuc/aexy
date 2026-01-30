"use client";

import Link from "next/link";
import {
  Bot,
  ChevronRight,
  Play,
  CheckCircle,
  XCircle,
  Plus,
  Zap,
} from "lucide-react";
import { useWorkspace } from "@/hooks/useWorkspace";
import { useWorkspaceAgents } from "@/hooks/useAgents";

export function AIAgentsWidget() {
  const { currentWorkspace } = useWorkspace();
  const { agents, isLoading } = useWorkspaceAgents(currentWorkspace?.id || null);

  if (isLoading) {
    return (
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6 animate-pulse">
        <div className="h-6 w-36 bg-slate-800 rounded mb-4" />
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-slate-800 rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  const activeAgents = agents?.filter((a) => a.is_active) || [];
  const totalExecutions = agents?.reduce((sum, a) => sum + a.total_executions, 0) || 0;
  const successfulExecutions = agents?.reduce((sum, a) => sum + a.successful_executions, 0) || 0;
  const successRate = totalExecutions > 0 ? Math.round((successfulExecutions / totalExecutions) * 100) : 0;

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-purple-500/10 rounded-lg">
            <Bot className="h-5 w-5 text-purple-400" />
          </div>
          <h3 className="text-lg font-semibold text-white">AI Agents</h3>
        </div>
        <Link
          href="/agents"
          className="text-purple-400 hover:text-purple-300 text-sm flex items-center gap-1 transition"
        >
          View All <ChevronRight className="w-4 h-4" />
        </Link>
      </div>
      <div className="p-6">
        {!currentWorkspace ? (
          <div className="text-center py-6">
            <div className="w-16 h-16 bg-slate-800 rounded-full flex items-center justify-center mx-auto mb-4">
              <Bot className="w-8 h-8 text-slate-600" />
            </div>
            <p className="text-slate-400 text-sm">
              Select a workspace to view AI agents.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Summary stats */}
            <div className="grid grid-cols-3 gap-3">
              <div className="text-center p-3 bg-slate-800/50 rounded-lg">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <Play className="h-3 w-3 text-green-400" />
                  <span className="text-xs text-slate-400">Active</span>
                </div>
                <p className="text-lg font-bold text-white">{activeAgents.length}</p>
              </div>
              <div className="text-center p-3 bg-slate-800/50 rounded-lg">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <Zap className="h-3 w-3 text-amber-400" />
                  <span className="text-xs text-slate-400">Runs</span>
                </div>
                <p className="text-lg font-bold text-white">{totalExecutions}</p>
              </div>
              <div className="text-center p-3 bg-slate-800/50 rounded-lg">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <CheckCircle className="h-3 w-3 text-emerald-400" />
                  <span className="text-xs text-slate-400">Success</span>
                </div>
                <p className="text-lg font-bold text-white">{successRate}%</p>
              </div>
            </div>

            {/* Agent list */}
            {activeAgents.length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs text-slate-500 uppercase tracking-wider">
                  Recent Agents
                </p>
                {activeAgents.slice(0, 4).map((agent) => (
                  <Link
                    key={agent.id}
                    href={`/agents/${agent.id}`}
                    className="flex items-center justify-between p-2 bg-slate-800/30 rounded-lg hover:bg-slate-800/50 transition"
                  >
                    <div className="flex items-center gap-2">
                      <Bot className="h-4 w-4 text-purple-400" />
                      <span className="text-sm text-slate-300">{agent.name}</span>
                      {agent.mention_handle && (
                        <span className="text-xs text-slate-500">@{agent.mention_handle}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {agent.total_executions > 0 ? (
                        <span className="text-xs text-slate-500">
                          {agent.successful_executions}/{agent.total_executions} runs
                        </span>
                      ) : (
                        <span className="text-xs text-slate-600">No runs yet</span>
                      )}
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="text-center py-4">
                <p className="text-slate-500 text-sm">No active agents yet.</p>
                <Link
                  href="/agents/new"
                  className="inline-flex items-center gap-1 mt-2 text-purple-400 hover:text-purple-300 text-sm transition"
                >
                  <Plus className="h-3 w-3" />
                  Create your first agent
                </Link>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
