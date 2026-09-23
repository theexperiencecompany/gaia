"use client";

import { Radio, RadioGroup } from "@heroui/radio";
import type { HilMode } from "@shared/chat";
import type { IntegrationPermissions } from "@/features/integrations/hooks/useIntegrationPermissions";
import { MODE_OPTIONS } from "@/features/integrations/utils/permissionCopy";

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
      value={permissions.mode}
      isDisabled={permissions.isSavingMode}
      onValueChange={(value) => permissions.changeMode(value as HilMode)}
    >
      {MODE_OPTIONS.map((option) => (
        <div
          key={option.mode}
          className={
            option.mode === permissions.mode
              ? "rounded-xl bg-zinc-800 p-2.5"
              : "rounded-xl p-2.5"
          }
        >
          <Radio
            value={option.mode}
            description={option.description}
            classNames={{
              base: "m-0 max-w-full items-start",
              labelWrapper: "ml-2",
              label: "text-sm text-zinc-200",
              description: "text-xs text-zinc-500",
            }}
          >
            {option.label}
          </Radio>
        </div>
      ))}
    </RadioGroup>
  </PermissionCard>
);
