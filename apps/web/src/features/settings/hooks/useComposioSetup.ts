"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { integrationKeys } from "@/features/integrations/api/queryKeys";
import {
  type ComposioIntegrationSetup,
  composioSetupApi,
} from "@/features/settings/api/composioSetupApi";
import { setupKeys } from "@/features/settings/api/queryKeys";
import { toast } from "@/lib/toast";

/** What a row's field starts as: the stored id, else the first auto-detected match. */
function initialDraft(row: ComposioIntegrationSetup): string {
  if (row.source === "stored") return row.auth_config_id ?? "";
  if (row.source === null) return row.detected[0]?.id ?? "";
  return "";
}

function storedIds(rows: ComposioIntegrationSetup[]): Record<string, string> {
  return Object.fromEntries(
    rows
      .filter((row) => row.source === "stored" && row.auth_config_id)
      .map((row) => [row.integration_id, row.auth_config_id ?? ""]),
  );
}

/**
 * The admin's Composio setup (GET /setup/composio) plus the per-integration
 * drafts the panel edits. Detected matches prefill unset rows, so saving
 * confirms them; a blank field falls back to the environment or GAIA default.
 */
export function useComposioSetup() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: setupKeys.composio,
    queryFn: composioSetupApi.fetchSetup,
    staleTime: 30_000,
  });
  const [edits, setEdits] = useState<Record<string, string>>({});

  const rows = query.data?.integrations;
  const drafts = useMemo(
    () =>
      Object.fromEntries(
        (rows ?? []).map((row) => [
          row.integration_id,
          edits[row.integration_id] ?? initialDraft(row),
        ]),
      ),
    [rows, edits],
  );
  const payload = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(drafts)
          .map(([id, value]) => [id, value.trim()] as const)
          .filter(([, value]) => value !== ""),
      ),
    [drafts],
  );
  const isDirty =
    rows !== undefined &&
    JSON.stringify(payload) !== JSON.stringify(storedIds(rows));

  const mutation = useMutation({
    mutationFn: composioSetupApi.saveAuthConfigs,
    onSuccess: (data) => {
      queryClient.setQueryData(setupKeys.composio, data);
      setEdits({});
      void queryClient.invalidateQueries({ queryKey: integrationKeys.all });
      toast.success("Integrations saved");
    },
  });

  return {
    setup: query.data,
    isLoading: query.isLoading,
    error: query.error,
    drafts,
    setDraft: (integrationId: string, value: string) =>
      setEdits((current) => ({ ...current, [integrationId]: value })),
    save: () => mutation.mutate(payload),
    isSaving: mutation.isPending,
    isDirty,
  };
}
