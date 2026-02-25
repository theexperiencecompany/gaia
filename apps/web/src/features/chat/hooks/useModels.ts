import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useUser } from "@/features/auth/hooks/useUser";
import { toast } from "@/lib/toast";

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
      // Check if this is an upgrade required error (403 with UPGRADE_REQUIRED code)
      const axiosError = error as {
        response?: {
          status?: number;
          data?: {
            detail?: { error_code?: string; message?: string } | string;
          };
        };
      };

      const isUpgradeRequired =
        axiosError.response?.status === 403 &&
        typeof axiosError.response?.data?.detail === "object" &&
        axiosError.response?.data?.detail?.error_code === "UPGRADE_REQUIRED";

      if (isUpgradeRequired) {
        toast.error("This model requires a Pro subscription", {
          action: {
            label: "Upgrade",
            onClick: () => {
              window.location.href = "/pricing";
            },
          },
        });
      } else {
        toast.error("Failed to select model");
      }
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
