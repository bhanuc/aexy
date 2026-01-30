"use client";

import { useState, useEffect } from "react";
import { AtSign, Check, X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCheckMentionHandle } from "@/hooks/useAgents";

interface BasicInfoStepProps {
  workspaceId: string;
  name: string;
  description: string;
  mentionHandle: string;
  onNameChange: (name: string) => void;
  onDescriptionChange: (description: string) => void;
  onMentionHandleChange: (handle: string) => void;
}

export function BasicInfoStep({
  workspaceId,
  name,
  description,
  mentionHandle,
  onNameChange,
  onDescriptionChange,
  onMentionHandleChange,
}: BasicInfoStepProps) {
  const [handleAvailable, setHandleAvailable] = useState<boolean | null>(null);
  const [handleError, setHandleError] = useState<string | null>(null);
  const { checkHandle, isChecking } = useCheckMentionHandle(workspaceId);

  // Debounced handle check
  useEffect(() => {
    if (!mentionHandle) {
      setHandleAvailable(null);
      setHandleError(null);
      return;
    }

    // Validate format
    if (!/^[a-z0-9_-]+$/i.test(mentionHandle)) {
      setHandleError("Only letters, numbers, underscores, and hyphens allowed");
      setHandleAvailable(false);
      return;
    }

    const timeoutId = setTimeout(async () => {
      try {
        const result = await checkHandle({ handle: mentionHandle });
        setHandleAvailable(result.available);
        setHandleError(result.available ? null : "This handle is already taken");
      } catch {
        setHandleError("Failed to check availability");
        setHandleAvailable(null);
      }
    }, 500);

    return () => clearTimeout(timeoutId);
  }, [mentionHandle, checkHandle]);

  // Auto-generate handle from name
  const generateHandle = (inputName: string) => {
    return inputName
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 30);
  };

  const handleNameChange = (newName: string) => {
    onNameChange(newName);
    // Auto-generate handle if it hasn't been manually edited
    if (!mentionHandle || mentionHandle === generateHandle(name)) {
      onMentionHandleChange(generateHandle(newName));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-white mb-2">
          Basic Information
        </h2>
        <p className="text-slate-400">
          Give your agent a name and description so you can easily identify it.
        </p>
      </div>

      <div className="space-y-4">
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Agent Name <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => handleNameChange(e.target.value)}
            placeholder="e.g., Support Bot, Sales Assistant"
            className="w-full px-4 py-3 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
            autoFocus
          />
          <p className="mt-1 text-sm text-slate-500">
            A descriptive name for your agent
          </p>
        </div>

        {/* Mention Handle */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Mention Handle
          </label>
          <div className="relative">
            <AtSign className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <input
              type="text"
              value={mentionHandle}
              onChange={(e) => onMentionHandleChange(e.target.value.toLowerCase())}
              placeholder="support-bot"
              className={cn(
                "w-full pl-10 pr-10 py-3 bg-slate-700 border rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2",
                handleError
                  ? "border-red-500 focus:ring-red-500"
                  : handleAvailable
                  ? "border-green-500 focus:ring-green-500"
                  : "border-slate-600 focus:ring-purple-500"
              )}
            />
            {/* Status indicator */}
            <div className="absolute right-3 top-1/2 -translate-y-1/2">
              {isChecking && (
                <Loader2 className="h-4 w-4 text-slate-400 animate-spin" />
              )}
              {!isChecking && handleAvailable === true && (
                <Check className="h-4 w-4 text-green-400" />
              )}
              {!isChecking && handleAvailable === false && (
                <X className="h-4 w-4 text-red-400" />
              )}
            </div>
          </div>
          {handleError ? (
            <p className="mt-1 text-sm text-red-400">{handleError}</p>
          ) : (
            <p className="mt-1 text-sm text-slate-500">
              Users can mention this agent using @{mentionHandle || "handle"}
            </p>
          )}
        </div>

        {/* Description */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Description
          </label>
          <textarea
            value={description}
            onChange={(e) => onDescriptionChange(e.target.value)}
            placeholder="Describe what this agent does..."
            rows={3}
            className="w-full px-4 py-3 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none"
          />
          <p className="mt-1 text-sm text-slate-500">
            Optional description to help you remember this agent's purpose
          </p>
        </div>
      </div>
    </div>
  );
}
