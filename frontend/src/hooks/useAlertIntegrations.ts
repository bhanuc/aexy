"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  alertIntegrationsApi,
  AlertIntegration,
  AlertIntegrationCreate,
  AlertIntegrationUpdate,
  AlertIntegrationWithSecret,
  AlertEventQuery,
} from "@/lib/api";

const key = (workspaceId: string | null) => ["alertIntegrations", workspaceId];

export function useAlertIntegrations(workspaceId: string | null) {
  return useQuery<AlertIntegration[]>({
    queryKey: key(workspaceId),
    queryFn: () => alertIntegrationsApi.list(workspaceId!),
    enabled: !!workspaceId,
  });
}

export function useAlertIntegrationEvents(
  workspaceId: string | null,
  integrationId: string | null,
  query: AlertEventQuery = { limit: 50 }
) {
  return useQuery({
    // The whole query is in the key. It used to be `limit` alone and never
    // forwarded `offset`, so the log capped out at one page however far you
    // tried to scroll.
    queryKey: ["alertIntegrationEvents", workspaceId, integrationId, query],
    queryFn: () => alertIntegrationsApi.listEvents(workspaceId!, integrationId!, query),
    enabled: !!workspaceId && !!integrationId,
    placeholderData: (previous) => previous,
  });
}

/** Every integration's alert history in one list. */
export function useAlertEvents(
  workspaceId: string | null,
  query: AlertEventQuery = { limit: 50 }
) {
  return useQuery({
    queryKey: ["alertEvents", workspaceId, query],
    queryFn: () => alertIntegrationsApi.listAllEvents(workspaceId!, query),
    enabled: !!workspaceId,
    placeholderData: (previous) => previous,
  });
}

export function useAlertIntegrationMutations(workspaceId: string | null) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: key(workspaceId) });

  const create = useMutation<AlertIntegrationWithSecret, unknown, AlertIntegrationCreate>({
    mutationFn: (data) => alertIntegrationsApi.create(workspaceId!, data),
    onSuccess: () => {
      invalidate();
      toast.success("Alert integration created");
    },
    onError: () => toast.error("Failed to create integration"),
  });

  const update = useMutation<AlertIntegration, unknown, { id: string; data: AlertIntegrationUpdate }>({
    mutationFn: ({ id, data }) => alertIntegrationsApi.update(workspaceId!, id, data),
    onSuccess: () => {
      invalidate();
      toast.success("Integration updated");
    },
    onError: () => toast.error("Failed to update integration"),
  });

  const rotateSecret = useMutation<AlertIntegrationWithSecret, unknown, string>({
    mutationFn: (id) => alertIntegrationsApi.rotateSecret(workspaceId!, id),
    onSuccess: () => {
      invalidate();
      toast.success("Signing secret rotated");
    },
    onError: () => toast.error("Failed to rotate secret"),
  });

  const remove = useMutation<void, unknown, string>({
    mutationFn: (id) => alertIntegrationsApi.remove(workspaceId!, id),
    onSuccess: () => {
      invalidate();
      toast.success("Integration deleted");
    },
    onError: () => toast.error("Failed to delete integration"),
  });

  return { create, update, rotateSecret, remove };
}
