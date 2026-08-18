"use client";

import { Radio, RadioGroup } from "@heroui/radio";
import type { HilMode } from "@shared/chat";
import type { IntegrationPermissions } from "@/features/integrations/hooks/useIntegrationPermissions";
import { MODE_OPTIONS } from "@/features/integrations/utils/permissionCopy";
import { cn } from "@/lib/utils";

import { PermissionCard } from "./PermissionCard";

interface PermissionModeDecisionProps {
  /** Named so it is unmistakable that this one choice reaches past it. */
  integrationName: string;
  permissions: IntegrationPermissions;
}

/**
 * The first of the modal's two decisions: what GAIA does when a picked tool
 * comes up. All three answers stay visible because the alternatives are the
 * explanation.
 */
export const PermissionModeDecision = ({
  integrationName,
  permissions,
}: PermissionModeDecisionProps) => (
  <PermissionCard
    title="How often GAIA asks"
    description={`Applies to every integration, not just ${integrationName}.`}
  >
    <RadioGroup
      aria-label="How often GAIA asks"
      classNames={{ wrapper: "gap-0.5" }}
      value={permissions.mode}
      isDisabled={permissions.isSavingMode}
      onValueChange={(value) => permissions.changeMode(value as HilMode)}
    >
      {MODE_OPTIONS.map((option) => (
        <Radio
          key={option.mode}
          value={option.mode}
          description={option.description}
          classNames={{
            base: cn(
              "m-0 max-w-full items-start gap-2 rounded-xl p-2.5",
              option.mode === permissions.mode && "bg-zinc-800",
            ),
            label: "text-sm text-zinc-200",
            description: "text-xs text-zinc-500",
          }}
        >
          {option.label}
        </Radio>
      ))}
    </RadioGroup>
  </PermissionCard>
);
