"use client";

import { Description, Radio, RadioGroup } from "@heroui/react";
import type { HilMode } from "@shared/chat";
import { toneVariants } from "@/components/shared/tone";
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
      className="gap-0.5"
      value={permissions.mode}
      isDisabled={permissions.isSavingMode}
      onChange={(value) => permissions.changeMode(value as HilMode)}
    >
      {MODE_OPTIONS.map((option) => (
        <Radio
          key={option.mode}
          value={option.mode}
          className={cn(
            "m-0 max-w-full items-start gap-2 rounded-xl p-2.5",
            option.mode === permissions.mode && "bg-zinc-800",
          )}
        >
          <Radio.Content
            className={toneVariants({ tone: "bright", className: "text-sm" })}
          >
            <Radio.Control>
              <Radio.Indicator />
            </Radio.Control>
            {option.label}
          </Radio.Content>
          {option.description ? (
            <Description
              className={toneVariants({ tone: "faint", className: "text-xs" })}
            >
              {option.description}
            </Description>
          ) : null}
        </Radio>
      ))}
    </RadioGroup>
  </PermissionCard>
);
