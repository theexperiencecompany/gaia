import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useUser } from "@/features/auth/hooks/useUser";

import {
  fetchAvailableModels,
  type ModelInfo,
  selectModel,
} from "../api/modelsApi";

export const useModels = () => {
  return useQuery({
    queryKey: ["models"],
    queryFn: fetchAvailableModels,
    staleTime: 60 * 60 * 1000, // 1 hour - models change infrequently
    gcTime: 60 * 60 * 1000, // 1 hour - keep in memory longer
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  });
};

export const useSelectModel = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: selectModel,
    onSuccess: (_data) => {
      // Invalidate user data to refresh selected model
      queryClient.invalidateQueries({ queryKey: ["user"] });
    },
    onError: (error) => {
      toast.error("Failed to select model");
      console.error("Model selection error:", error);
    },
  });
};

export const useCurrentUserModel = (): ModelInfo | null => {
  const { data: models } = useModels();
  const user = useUser();

  return (
    models?.find((model) => model.model_id === user.selected_model) || null
  );
};
