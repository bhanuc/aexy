"use client";

import { useState, useEffect } from "react";
import {
  Bot,
  ChevronDown,
  Clock,
  Variable,
  Plus,
  Trash2,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CRMAgent } from "@/lib/api";
import { useAgents } from "@/hooks/useAgents";

/**
 * Configuration for an agent node in the workflow builder.
 * This is stored in the node's `data` field.
 */
export interface AgentNodeData {
  label: string;
  agent_id: string | null;
  input_mapping: Record<string, string>;
  output_variable: string | null;
  wait_for_completion: boolean;
  timeout_seconds: number;
}

interface AgentNodeEditorProps {
  workspaceId: string;
  data: Partial<AgentNodeData>;
  onChange: (data: AgentNodeData) => void;
  className?: string;
}

const DEFAULT_DATA: AgentNodeData = {
  label: "AI Agent",
  agent_id: null,
  input_mapping: {},
  output_variable: null,
  wait_for_completion: true,
  timeout_seconds: 300,
};

// Common context variables available in workflows
const AVAILABLE_CONTEXT_PATHS = [
  { path: "record.id", label: "Record ID" },
  { path: "record.values.name", label: "Record Name" },
  { path: "record.values.email", label: "Record Email" },
  { path: "record.values.company", label: "Record Company" },
  { path: "record.owner_id", label: "Record Owner ID" },
  { path: "trigger_data.event_type", label: "Trigger Event Type" },
  { path: "trigger_data.changed_field", label: "Changed Field" },
  { path: "trigger_data.old_value", label: "Old Value" },
  { path: "trigger_data.new_value", label: "New Value" },
];

export function AgentNodeEditor({
  workspaceId,
  data,
  onChange,
  className,
}: AgentNodeEditorProps) {
  const [nodeData, setNodeData] = useState<AgentNodeData>({
    ...DEFAULT_DATA,
    ...data,
  });

  const { agents, isLoading: isLoadingAgents } = useAgents(workspaceId, {
    isActive: true,
  });

  // Sync internal state with props
  useEffect(() => {
    setNodeData({
      ...DEFAULT_DATA,
      ...data,
    });
  }, [data]);

  const handleChange = (updates: Partial<AgentNodeData>) => {
    const newData = { ...nodeData, ...updates };
    setNodeData(newData);
    onChange(newData);
  };

  const selectedAgent = agents.find((a) => a.id === nodeData.agent_id);

  // Update label when agent changes
  useEffect(() => {
    if (selectedAgent && nodeData.label === "AI Agent") {
      handleChange({ label: `Run ${selectedAgent.name}` });
    }
  }, [selectedAgent?.id]);

  return (
    <div className={cn("space-y-4", className)}>
      {/* Agent Selection */}
      <div className="space-y-2">
        <label className="text-sm font-medium">Agent</label>
        {isLoadingAgents ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading agents...
          </div>
        ) : (
          <select
            value={nodeData.agent_id || ""}
            onChange={(e) => handleChange({ agent_id: e.target.value || null })}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
          >
            <option value="">Select an agent...</option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name} ({agent.agent_type})
              </option>
            ))}
          </select>
        )}
        {selectedAgent && (
          <div className="flex items-start gap-2 p-2 rounded-md bg-muted/50">
            <Bot className="h-4 w-4 mt-0.5 text-primary flex-shrink-0" />
            <div className="text-xs text-muted-foreground">
              {selectedAgent.description || `${selectedAgent.agent_type} agent`}
            </div>
          </div>
        )}
      </div>

      {/* Node Label */}
      <div className="space-y-2">
        <label className="text-sm font-medium">Node Label</label>
        <input
          type="text"
          value={nodeData.label}
          onChange={(e) => handleChange({ label: e.target.value })}
          placeholder="AI Agent"
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
      </div>

      {/* Input Mapping */}
      <InputMappingEditor
        mapping={nodeData.input_mapping}
        onChange={(input_mapping) => handleChange({ input_mapping })}
      />

      {/* Output Variable */}
      <div className="space-y-2">
        <label className="text-sm font-medium">Output Variable (optional)</label>
        <div className="flex items-center gap-2">
          <Variable className="h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            value={nodeData.output_variable || ""}
            onChange={(e) => handleChange({ output_variable: e.target.value || null })}
            placeholder="agent_result"
            className="flex-1 rounded-md border bg-background px-3 py-2 text-sm font-mono"
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Store the agent&apos;s output in a workflow variable for use in subsequent nodes
        </p>
      </div>

      {/* Execution Options */}
      <div className="space-y-3 p-3 rounded-lg border bg-muted/30">
        <h4 className="text-sm font-medium">Execution Options</h4>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={nodeData.wait_for_completion}
            onChange={(e) => handleChange({ wait_for_completion: e.target.checked })}
            className="rounded"
          />
          Wait for agent completion
        </label>

        {nodeData.wait_for_completion && (
          <div className="flex items-center gap-2 ml-6">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <input
              type="number"
              value={nodeData.timeout_seconds}
              onChange={(e) =>
                handleChange({ timeout_seconds: parseInt(e.target.value) || 300 })
              }
              min={30}
              max={3600}
              className="w-20 rounded-md border bg-background px-2 py-1 text-sm"
            />
            <span className="text-sm text-muted-foreground">seconds timeout</span>
          </div>
        )}

        {!nodeData.wait_for_completion && (
          <p className="text-xs text-muted-foreground ml-6">
            The workflow will continue immediately without waiting for the agent to finish
          </p>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// Input Mapping Editor Sub-component
// =============================================================================

interface InputMappingEditorProps {
  mapping: Record<string, string>;
  onChange: (mapping: Record<string, string>) => void;
}

function InputMappingEditor({ mapping, onChange }: InputMappingEditorProps) {
  const [newKey, setNewKey] = useState("");
  const [newPath, setNewPath] = useState("");

  const entries = Object.entries(mapping);

  const handleAdd = () => {
    if (!newKey || !newPath) return;
    onChange({ ...mapping, [newKey]: newPath });
    setNewKey("");
    setNewPath("");
  };

  const handleRemove = (key: string) => {
    const newMapping = { ...mapping };
    delete newMapping[key];
    onChange(newMapping);
  };

  const handleUpdate = (oldKey: string, newKey: string, path: string) => {
    const newMapping = { ...mapping };
    if (oldKey !== newKey) {
      delete newMapping[oldKey];
    }
    newMapping[newKey] = path;
    onChange(newMapping);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium">Input Mapping (optional)</label>
      </div>
      <p className="text-xs text-muted-foreground">
        Map workflow context to agent input variables
      </p>

      {/* Existing Mappings */}
      {entries.length > 0 && (
        <div className="space-y-2">
          {entries.map(([key, path]) => (
            <div key={key} className="flex items-center gap-2">
              <input
                type="text"
                value={key}
                onChange={(e) => handleUpdate(key, e.target.value, path)}
                placeholder="Variable name"
                className="flex-1 rounded-md border bg-background px-2 py-1.5 text-sm font-mono"
              />
              <span className="text-muted-foreground">=</span>
              <select
                value={path}
                onChange={(e) => handleUpdate(key, key, e.target.value)}
                className="flex-1 rounded-md border bg-background px-2 py-1.5 text-sm"
              >
                <option value="">Select context path...</option>
                {AVAILABLE_CONTEXT_PATHS.map((cp) => (
                  <option key={cp.path} value={cp.path}>
                    {cp.label}
                  </option>
                ))}
                <option value={path} disabled={AVAILABLE_CONTEXT_PATHS.some(cp => cp.path === path)}>
                  {path} (custom)
                </option>
              </select>
              <button
                type="button"
                onClick={() => handleRemove(key)}
                className="p-1.5 rounded-md text-red-500 hover:bg-red-50"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add New Mapping */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder="Variable name"
          className="flex-1 rounded-md border bg-background px-2 py-1.5 text-sm font-mono"
        />
        <span className="text-muted-foreground">=</span>
        <select
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
          className="flex-1 rounded-md border bg-background px-2 py-1.5 text-sm"
        >
          <option value="">Select context path...</option>
          {AVAILABLE_CONTEXT_PATHS.map((cp) => (
            <option key={cp.path} value={cp.path}>
              {cp.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleAdd}
          disabled={!newKey || !newPath}
          className="p-1.5 rounded-md text-primary hover:bg-primary/10 disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// =============================================================================
// Agent Node Preview (for workflow canvas)
// =============================================================================

interface AgentNodePreviewProps {
  data: Partial<AgentNodeData>;
  selected?: boolean;
  className?: string;
}

export function AgentNodePreview({
  data,
  selected,
  className,
}: AgentNodePreviewProps) {
  return (
    <div
      className={cn(
        "rounded-lg border-2 bg-card px-4 py-3 min-w-[200px] shadow-sm transition-all",
        selected ? "border-primary ring-2 ring-primary/20" : "border-pink-500/50",
        className
      )}
    >
      <div className="flex items-center gap-2">
        <div className="rounded-lg bg-pink-500/10 p-2">
          <Bot className="h-5 w-5 text-pink-500" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm truncate">
            {data.label || "AI Agent"}
          </div>
          {data.agent_id && (
            <div className="text-xs text-muted-foreground truncate">
              {data.wait_for_completion ? "Wait for completion" : "Fire and forget"}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
