import type {
  UserFeatureFlagListResponse,
  UserFeatureFlagResponse,
} from "@shared/api/generated";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { featureFlagsApi } from "@/features/settings/api/featureFlagsApi";

const FEATURE_FLAGS_KEY = ["settings", "feature-flags"] as const;

interface FeatureChoice {
  key: string;
  enabled: boolean;
}

/** The flags the API lets this user toggle, each with the value in effect for them. */
export function useFeatureFlags() {
  const { data, isLoading } = useQuery({
    queryKey: FEATURE_FLAGS_KEY,
    queryFn: featureFlagsApi.list,
  });
  return {
    features: data?.features ?? [],
    isLoading,
    isEmpty: data?.features.length === 0,
  };
}

/**
 * Flip one flag optimistically. A failure puts back only that flag's previous
 * value, so a concurrent toggle of another flag is never undone with it.
 */
export function useFeatureToggle() {
  const qc = useQueryClient();

  const setFlag = (key: string, change: Partial<UserFeatureFlagResponse>) =>
    qc.setQueryData<UserFeatureFlagListResponse>(
      FEATURE_FLAGS_KEY,
      (current) =>
        current && {
          features: current.features.map((feature) =>
            feature.key === key ? { ...feature, ...change } : feature,
          ),
        },
    );

  const mutation = useMutation({
    mutationFn: ({ key, enabled }: FeatureChoice) =>
      featureFlagsApi.setEnabled(key, enabled),
    // The in-flight list is cancelled first, or it can land after the click and undo it.
    onMutate: async ({ key, enabled }) => {
      await qc.cancelQueries({ queryKey: FEATURE_FLAGS_KEY });
      const previousEnabled = qc
        .getQueryData<UserFeatureFlagListResponse>(FEATURE_FLAGS_KEY)
        ?.features.find((feature) => feature.key === key)?.enabled;
      setFlag(key, { enabled });
      return { previousEnabled };
    },
    onSuccess: (feature) => setFlag(feature.key, feature),
    onError: (_error, { key }, context) => {
      if (context?.previousEnabled !== undefined) {
        setFlag(key, { enabled: context.previousEnabled });
      }
    },
  });

  return {
    setEnabled: (key: string, enabled: boolean) =>
      mutation.mutate({ key, enabled }),
    isSaving: mutation.isPending,
  };
}
