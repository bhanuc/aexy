/**
 * Platform-wide Automations hooks.
 *
 * Provides generic automation hooks that support all Aexy modules.
 * For backwards compatibility, useCRMAutomations in useCRM.ts uses
 * these hooks internally with module='crm'.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  automationsApi,
  Automation,
  AutomationRun,
  AutomationModule,
  AutomationTriggerType,
  AutomationActionType,
} from "@/lib/api";

// Re-export types for convenience
export type { Automation, AutomationRun, AutomationModule };

export interface UseAutomationsOptions {
  module?: AutomationModule;
  object_id?: string;
  is_active?: boolean;
}

/**
 * Hook for managing automations across all modules.
 *
 * @param workspaceId - The workspace ID
 * @param options - Filter options (module, object_id, is_active)
 * @returns Automations and mutation functions
 */
export function useAutomations(
  workspaceId: string | null,
  options?: UseAutomationsOptions
) {
  const queryClient = useQueryClient();

  const {
    data: automations,
    isLoading,
    error,
    refetch,
  } = useQuery<Automation[]>({
    queryKey: ["automations", workspaceId, options],
    queryFn: () => automationsApi.list(workspaceId!, options),
    enabled: !!workspaceId,
  });

  const createMutation = useMutation({
    mutationFn: (data: {
      name: string;
      module: AutomationModule;
      trigger_type: string;
      description?: string;
      module_config?: Record<string, unknown>;
      object_id?: string;
      trigger_config?: Record<string, unknown>;
      conditions?: Record<string, unknown>[];
      actions: { type: string; config: Record<string, unknown> }[];
      error_handling?: "stop" | "continue" | "retry";
      run_limit_per_month?: number;
      is_active?: boolean;
    }) => automationsApi.create(workspaceId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["automations", workspaceId] });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      automationId,
      data,
    }: {
      automationId: string;
      data: Partial<{
        name: string;
        description: string;
        module_config: Record<string, unknown>;
        trigger_config: Record<string, unknown>;
        conditions: Record<string, unknown>[];
        actions: { type: string; config: Record<string, unknown> }[];
        is_active: boolean;
        run_limit_per_month: number;
        error_handling: "stop" | "continue" | "retry";
      }>;
    }) => automationsApi.update(workspaceId!, automationId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["automations", workspaceId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (automationId: string) => automationsApi.delete(workspaceId!, automationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["automations", workspaceId] });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: (automationId: string) => automationsApi.toggle(workspaceId!, automationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["automations", workspaceId] });
    },
  });

  const triggerMutation = useMutation({
    mutationFn: ({ automationId, recordId }: { automationId: string; recordId?: string }) =>
      automationsApi.trigger(workspaceId!, automationId, recordId),
  });

  return {
    automations: automations || [],
    isLoading,
    error,
    refetch,
    createAutomation: createMutation.mutateAsync,
    updateAutomation: updateMutation.mutateAsync,
    deleteAutomation: deleteMutation.mutateAsync,
    toggleAutomation: toggleMutation.mutateAsync,
    triggerAutomation: triggerMutation.mutateAsync,
    isCreating: createMutation.isPending,
    isUpdating: updateMutation.isPending,
    isDeleting: deleteMutation.isPending,
    isToggling: toggleMutation.isPending,
    isTriggering: triggerMutation.isPending,
  };
}

/**
 * Hook for fetching automation runs.
 *
 * @param workspaceId - The workspace ID
 * @param automationId - The automation ID
 * @param params - Pagination params
 * @returns Automation runs
 */
export function useAutomationRuns(
  workspaceId: string | null,
  automationId: string | null,
  params?: { skip?: number; limit?: number }
) {
  const {
    data: runs,
    isLoading,
    error,
    refetch,
  } = useQuery<AutomationRun[]>({
    queryKey: ["automationRuns", workspaceId, automationId, params],
    queryFn: () => automationsApi.listRuns(workspaceId!, automationId!, params),
    enabled: !!workspaceId && !!automationId,
  });

  return {
    runs: runs || [],
    isLoading,
    error,
    refetch,
  };
}

/**
 * Hook for fetching a single automation.
 *
 * @param workspaceId - The workspace ID
 * @param automationId - The automation ID
 * @returns Automation details
 */
export function useAutomation(workspaceId: string | null, automationId: string | null) {
  const {
    data: automation,
    isLoading,
    error,
    refetch,
  } = useQuery<Automation>({
    queryKey: ["automation", workspaceId, automationId],
    queryFn: () => automationsApi.get(workspaceId!, automationId!),
    enabled: !!workspaceId && !!automationId,
  });

  return {
    automation,
    isLoading,
    error,
    refetch,
  };
}

/**
 * Hook for fetching trigger registry.
 *
 * @param workspaceId - The workspace ID
 * @returns All available triggers by module
 */
export function useAutomationTriggerRegistry(workspaceId: string | null) {
  const {
    data,
    isLoading,
    error,
  } = useQuery<{ triggers: Record<string, string[]> }>({
    queryKey: ["automationTriggers", workspaceId],
    queryFn: () => automationsApi.getTriggerRegistry(workspaceId!),
    enabled: !!workspaceId,
  });

  return {
    triggers: data?.triggers || {},
    isLoading,
    error,
  };
}

/**
 * Hook for fetching action registry.
 *
 * @param workspaceId - The workspace ID
 * @returns All available actions by module
 */
export function useAutomationActionRegistry(workspaceId: string | null) {
  const {
    data,
    isLoading,
    error,
  } = useQuery<{ actions: Record<string, string[]> }>({
    queryKey: ["automationActions", workspaceId],
    queryFn: () => automationsApi.getActionRegistry(workspaceId!),
    enabled: !!workspaceId,
  });

  return {
    actions: data?.actions || {},
    isLoading,
    error,
  };
}

/**
 * Hook for fetching triggers for a specific module.
 *
 * @param workspaceId - The workspace ID
 * @param module - The module name
 * @returns Triggers for the module
 */
export function useModuleTriggers(workspaceId: string | null, module: string | null) {
  const {
    data,
    isLoading,
    error,
  } = useQuery<{ module: string; triggers: string[] }>({
    queryKey: ["moduleTriggers", workspaceId, module],
    queryFn: () => automationsApi.getModuleTriggers(workspaceId!, module!),
    enabled: !!workspaceId && !!module,
  });

  return {
    triggers: data?.triggers || [],
    isLoading,
    error,
  };
}

/**
 * Hook for fetching actions for a specific module.
 *
 * @param workspaceId - The workspace ID
 * @param module - The module name
 * @returns Actions for the module
 */
export function useModuleActions(workspaceId: string | null, module: string | null) {
  const {
    data,
    isLoading,
    error,
  } = useQuery<{ module: string; actions: string[] }>({
    queryKey: ["moduleActions", workspaceId, module],
    queryFn: () => automationsApi.getModuleActions(workspaceId!, module!),
    enabled: !!workspaceId && !!module,
  });

  return {
    actions: data?.actions || [],
    isLoading,
    error,
  };
}
