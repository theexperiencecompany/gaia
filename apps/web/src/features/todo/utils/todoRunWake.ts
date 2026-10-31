import type { TriggerEventLabel } from "@shared/todos";
import { getTriggerDisplayInfoBySlug } from "@/features/workflows/triggers/registryDisplay";
import type { TriggerConfigDraft } from "@/features/workflows/triggers/types";

/** Words for one watched event, from the trigger display registry; its id when it has none. */
export const triggerEventLabel: TriggerEventLabel = (triggerName) =>
  getTriggerDisplayInfoBySlug(triggerName, {
    type: "integration",
    trigger_name: triggerName,
  } as TriggerConfigDraft)?.label ?? `on ${triggerName}`;
