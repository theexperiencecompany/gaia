import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { settingsApi } from "@/features/settings/api/settings-api";
import {
  fetchAvailableModels,
  type ModelInfo,
  selectModel,
} from "../api/models-api";

export const modelKeys = {
  all: ["models"] as const,
  list: () => [...modelKeys.all, "list"] as const,
};

export const profileKeys = {
  all: ["profile"] as const,
  detail: () => [...profileKeys.all, "detail"] as const,
};

export function useModels() {
  return useQuery({
    queryKey: modelKeys.list(),
    queryFn: fetchAvailableModels,
    staleTime: 60 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
  });
}

export function useProfile() {
  return useQuery({
    queryKey: profileKeys.detail(),
    queryFn: () => settingsApi.getProfile(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useCurrentModel(): ModelInfo | null {
  const { data: models } = useModels();
  const { data: profile } = useProfile();

  if (!models) return null;

  if (profile?.selected_model) {
    const found = models.find((m) => m.model_id === profile.selected_model);
    if (found) return found;
  }

  return models.find((m) => m.is_default) ?? null;
}

export function useSelectModel() {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: selectModel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: profileKeys.detail() });
    },
  });

  const select = useCallback(
    (modelId: string) => {
      mutation.mutate(modelId);
    },
    [mutation],
  );

  return { select, isPending: mutation.isPending };
}
