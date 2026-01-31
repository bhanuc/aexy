"use client";

import { useState } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  ChevronLeft,
  Bot,
  Play,
  Pause,
  Settings,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  Zap,
  ChevronRight,
  Loader2,
  Target,
  Mail,
  Database,
  Sparkles,
  X,
  Wrench,
} from "lucide-react";
import { useWorkspace } from "@/hooks/useWorkspace";
import { useAgent, useAgentExecutions, useAgentExecution, useAgentTools } from "@/hooks/useAgents";
import { useAuth } from "@/hooks/useAuth";
import { CRMAgentExecution } from "@/lib/api";

// Run Agent Dialog Component
function RunAgentDialog({
  isOpen,
  onClose,
  onRun,
  isRunning,
  agentName,
  tools,
}: {
  isOpen: boolean;
  onClose: () => void;
  onRun: (context: Record<string, unknown>) => void;
  isRunning: boolean;
  agentName: string;
  tools: string[];
}) {
  const [task, setTask] = useState("");

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onRun({ task: task || `Execute the ${agentName} agent` });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-lg mx-4">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-500/20 rounded-lg">
              <Zap className="h-5 w-5 text-green-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Run {agentName}</h2>
              <p className="text-sm text-slate-400">Provide context for the agent</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 hover:text-white transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="p-5 space-y-5">
          {/* Task Input */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Task Description
            </label>
            <textarea
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="e.g., Search for contacts in the tech industry and draft a personalized email..."
              className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-green-500/50 focus:border-green-500 resize-none"
              rows={4}
              autoFocus
            />
            <p className="mt-2 text-xs text-slate-500">
              Be specific about what you want the agent to do. The agent will use its available tools to complete the task.
            </p>
          </div>

          {/* Available Tools */}
          {tools.length > 0 && (
            <div>
              <div className="flex items-center gap-2 text-sm text-slate-400 mb-2">
                <Wrench className="h-4 w-4" />
                <span>Available Tools</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {tools.map((tool) => (
                  <span
                    key={tool}
                    className="px-2 py-1 bg-slate-800 text-slate-400 rounded text-xs"
                  >
                    {tool.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-slate-400 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isRunning}
              className="flex items-center gap-2 px-5 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isRunning ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Running...
                </>
              ) : (
                <>
                  <Zap className="h-4 w-4" />
                  Run Agent
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

const agentTypeLabels: Record<string, { label: string; icon: typeof Bot; color: string }> = {
  sales_outreach: { label: "Sales Outreach", icon: Target, color: "text-green-400 bg-green-500/20" },
  lead_scoring: { label: "Lead Scoring", icon: Sparkles, color: "text-yellow-400 bg-yellow-500/20" },
  email_drafter: { label: "Email Drafter", icon: Mail, color: "text-blue-400 bg-blue-500/20" },
  data_enrichment: { label: "Data Enrichment", icon: Database, color: "text-purple-400 bg-purple-500/20" },
  custom: { label: "Custom Agent", icon: Settings, color: "text-slate-400 bg-slate-500/20" },
};

const statusColors: Record<string, { bg: string; text: string; icon: typeof CheckCircle }> = {
  pending: { bg: "bg-slate-500/20", text: "text-slate-400", icon: Clock },
  running: { bg: "bg-blue-500/20", text: "text-blue-400", icon: Loader2 },
  completed: { bg: "bg-green-500/20", text: "text-green-400", icon: CheckCircle },
  failed: { bg: "bg-red-500/20", text: "text-red-400", icon: XCircle },
  cancelled: { bg: "bg-yellow-500/20", text: "text-yellow-400", icon: AlertCircle },
};

function ExecutionCard({
  execution,
  isSelected,
  onClick,
}: {
  execution: CRMAgentExecution;
  isSelected: boolean;
  onClick: () => void;
}) {
  const status = statusColors[execution.status] || statusColors.pending;
  const StatusIcon = status.icon;

  return (
    <div
      onClick={onClick}
      className={`p-4 rounded-xl border cursor-pointer transition-colors ${
        isSelected
          ? "border-blue-500 bg-blue-500/10"
          : "border-slate-700 bg-slate-800/50 hover:border-slate-600"
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <StatusIcon className={`h-4 w-4 ${status.text} ${execution.status === "running" ? "animate-spin" : ""}`} />
          <span className={`px-2 py-0.5 rounded text-xs ${status.bg} ${status.text}`}>
            {execution.status}
          </span>
        </div>
        <span className="text-xs text-slate-500">
          {new Date(execution.created_at).toLocaleString()}
        </span>
      </div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-400">
          {execution.steps.length} steps
        </span>
        {execution.duration_ms && (
          <span className="text-slate-500">
            {(execution.duration_ms / 1000).toFixed(1)}s
          </span>
        )}
      </div>
    </div>
  );
}

function ExecutionDetail({ execution }: { execution: CRMAgentExecution }) {
  return (
    <div className="space-y-4">
      {/* Status */}
      <div className="flex items-center gap-4">
        <div className={`px-3 py-1 rounded-lg ${statusColors[execution.status]?.bg} ${statusColors[execution.status]?.text}`}>
          {execution.status}
        </div>
        {execution.duration_ms && (
          <span className="text-slate-400">
            Duration: {(execution.duration_ms / 1000).toFixed(2)}s
          </span>
        )}
      </div>

      {/* Error Message */}
      {execution.error_message && (
        <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
          <div className="text-sm font-medium text-red-400 mb-1">Error</div>
          <div className="text-sm text-red-300">{execution.error_message}</div>
        </div>
      )}

      {/* Output Result */}
      {execution.output_result && (
        <div className="p-4 bg-slate-800/50 border border-slate-700 rounded-lg">
          <div className="text-sm font-medium text-slate-300 mb-2">Output</div>
          <pre className="text-sm text-slate-400 overflow-auto max-h-48">
            {JSON.stringify(execution.output_result, null, 2)}
          </pre>
        </div>
      )}

      {/* Steps */}
      <div>
        <h4 className="text-sm font-medium text-slate-300 mb-3">Execution Steps</h4>
        <div className="space-y-3">
          {execution.steps.map((step, index) => (
            <div
              key={index}
              className="p-4 bg-slate-800/50 border border-slate-700 rounded-lg"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center text-xs text-slate-400">
                  {step.step_number || index + 1}
                </span>
                {step.tool_name && (
                  <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs">
                    {step.tool_name}
                  </span>
                )}
              </div>
              {step.thought && (
                <div className="text-sm text-slate-300 mb-2 italic">
                  &ldquo;{step.thought}&rdquo;
                </div>
              )}
              {step.tool_input && (
                <details className="text-sm">
                  <summary className="text-slate-500 cursor-pointer hover:text-slate-400">
                    Input
                  </summary>
                  <pre className="mt-2 p-2 bg-slate-900 rounded text-slate-400 overflow-auto">
                    {JSON.stringify(step.tool_input, null, 2)}
                  </pre>
                </details>
              )}
              {step.tool_output && (
                <details className="text-sm mt-2">
                  <summary className="text-slate-500 cursor-pointer hover:text-slate-400">
                    Output
                  </summary>
                  <pre className="mt-2 p-2 bg-slate-900 rounded text-slate-400 overflow-auto max-h-32">
                    {step.tool_output}
                  </pre>
                </details>
              )}
            </div>
          ))}
          {execution.steps.length === 0 && execution.status === "running" && (
            <div className="text-center py-8 text-slate-500">
              <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2" />
              Agent is thinking...
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function AgentDetailPage() {
  const router = useRouter();
  const params = useParams();
  const agentId = params.agentId as string;
  const { currentWorkspace } = useWorkspace();
  const workspaceId = currentWorkspace?.id || null;
  const { user, logout } = useAuth();

  const { agent, isLoading, executeAgent, isExecuting } = useAgent(workspaceId, agentId);
  const { executions, isLoading: isLoadingExecutions } = useAgentExecutions(workspaceId, agentId);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null);
  const [showRunDialog, setShowRunDialog] = useState(false);
  const { execution: selectedExecution } = useAgentExecution(
    workspaceId,
    agentId,
    selectedExecutionId
  );

  const typeInfo = agent ? (agentTypeLabels[agent.agent_type] || agentTypeLabels.custom) : agentTypeLabels.custom;
  const Icon = typeInfo.icon;

  const handleExecute = async (context: Record<string, unknown>) => {
    try {
      const execution = await executeAgent({ context });
      setSelectedExecutionId(execution.id);
      setShowRunDialog(false);
    } catch (error) {
      console.error("Failed to execute agent:", error);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950">
<div className="flex items-center justify-center p-8" style={{ minHeight: 'calc(100vh - 64px)' }}>
          <Loader2 className="h-8 w-8 text-blue-500 animate-spin" />
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="min-h-screen bg-slate-950">
<div className="flex items-center justify-center p-8" style={{ minHeight: 'calc(100vh - 64px)' }}>
          <div className="text-center">
            <Bot className="h-12 w-12 text-slate-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-white mb-2">Agent not found</h3>
            <button
              onClick={() => router.push("/crm/agents")}
              className="text-blue-400 hover:text-blue-300"
            >
              Back to agents
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950">
<div className="p-8">
        <div className="max-w-7xl mx-auto">
          {/* Header */}
          <div className="flex items-center gap-4 mb-8">
          <button
            onClick={() => router.push("/crm/agents")}
            className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 hover:text-white transition-colors"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          <div className={`p-3 rounded-xl ${agent.is_active ? typeInfo.color : "bg-slate-700 text-slate-400"}`}>
            <Icon className="h-6 w-6" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold text-white">{agent.name}</h1>
              {agent.is_system && (
                <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 text-xs rounded-full">
                  System
                </span>
              )}
            </div>
            <p className="text-sm text-slate-400">{typeInfo.label}</p>
          </div>
          <button
            onClick={() => setShowRunDialog(true)}
            disabled={isExecuting || !agent.is_active}
            className="flex items-center gap-2 px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isExecuting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Running...
              </>
            ) : (
              <>
                <Zap className="h-4 w-4" />
                Run Agent
              </>
            )}
          </button>
        </div>

        {/* Run Agent Dialog */}
        <RunAgentDialog
          isOpen={showRunDialog}
          onClose={() => setShowRunDialog(false)}
          onRun={handleExecute}
          isRunning={isExecuting}
          agentName={agent.name}
          tools={agent.tools}
        />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Left Column - Agent Info */}
          <div className="space-y-6">
            {/* Stats */}
            <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-5">
              <h3 className="text-lg font-medium text-white mb-4">Statistics</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-2xl font-bold text-white">{agent.total_executions}</div>
                  <div className="text-sm text-slate-400">Total Runs</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-green-400">
                    {agent.total_executions > 0
                      ? Math.round((agent.successful_executions / agent.total_executions) * 100)
                      : 0}%
                  </div>
                  <div className="text-sm text-slate-400">Success Rate</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-white">
                    {agent.avg_duration_ms > 0 ? (agent.avg_duration_ms / 1000).toFixed(1) : 0}s
                  </div>
                  <div className="text-sm text-slate-400">Avg Duration</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-red-400">{agent.failed_executions}</div>
                  <div className="text-sm text-slate-400">Failed</div>
                </div>
              </div>
            </div>

            {/* Configuration */}
            <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-5">
              <h3 className="text-lg font-medium text-white mb-4">Configuration</h3>
              <div className="space-y-3 text-sm">
                <div>
                  <div className="text-slate-500">Model</div>
                  <div className="text-slate-300">{agent.model}</div>
                </div>
                <div>
                  <div className="text-slate-500">Max Iterations</div>
                  <div className="text-slate-300">{agent.max_iterations}</div>
                </div>
                <div>
                  <div className="text-slate-500">Timeout</div>
                  <div className="text-slate-300">{agent.timeout_seconds}s</div>
                </div>
                {agent.goal && (
                  <div>
                    <div className="text-slate-500">Goal</div>
                    <div className="text-slate-300">{agent.goal}</div>
                  </div>
                )}
              </div>
            </div>

            {/* Tools */}
            <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-5">
              <h3 className="text-lg font-medium text-white mb-4">Tools</h3>
              <div className="flex flex-wrap gap-2">
                {agent.tools.map((tool) => (
                  <span
                    key={tool}
                    className="px-2 py-1 bg-slate-700 text-slate-300 rounded text-sm"
                  >
                    {tool.replace(/_/g, " ")}
                  </span>
                ))}
                {agent.tools.length === 0 && (
                  <span className="text-slate-500">No tools configured</span>
                )}
              </div>
            </div>
          </div>

          {/* Middle Column - Execution History */}
          <div>
            <h3 className="text-lg font-medium text-white mb-4">Execution History</h3>
            <div className="space-y-3 max-h-[600px] overflow-y-auto">
              {isLoadingExecutions ? (
                <div className="text-center py-8 text-slate-500">
                  <Loader2 className="h-6 w-6 animate-spin mx-auto" />
                </div>
              ) : executions.length === 0 ? (
                <div className="text-center py-8">
                  <Clock className="h-8 w-8 text-slate-600 mx-auto mb-2" />
                  <p className="text-slate-500">No executions yet</p>
                  <p className="text-xs text-slate-600 mt-1">Run the agent to see execution history</p>
                </div>
              ) : (
                executions.map((execution) => (
                  <ExecutionCard
                    key={execution.id}
                    execution={execution}
                    isSelected={selectedExecutionId === execution.id}
                    onClick={() => setSelectedExecutionId(execution.id)}
                  />
                ))
              )}
            </div>
          </div>

          {/* Right Column - Execution Detail */}
          <div>
            <h3 className="text-lg font-medium text-white mb-4">Execution Details</h3>
            {selectedExecution ? (
              <ExecutionDetail execution={selectedExecution} />
            ) : (
              <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-8 text-center">
                <Bot className="h-8 w-8 text-slate-600 mx-auto mb-2" />
                <p className="text-slate-500">Select an execution to view details</p>
              </div>
            )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
