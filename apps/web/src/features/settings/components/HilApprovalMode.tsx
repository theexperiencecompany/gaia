"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Select, SelectItem } from "@heroui/select";
import type { HilMode } from "@shared/chat";
import { useRouter } from "next/navigation";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import {
  ALWAYS_ASKS_LABEL,
  ALWAYS_ASKS_NOTE,
  APPROVAL_MODES,
  APPROVALS_SECTION_DESCRIPTION,
} from "@/features/settings/config/approvalModes";
import { useHilPreferences } from "@/features/settings/hooks/useHilPreferences";
import { toast } from "@/lib/toast";

export function HilApprovalMode() {
  const router = useRouter();
  const { mode, isLoading, isSavingMode, setMode } = useHilPreferences();

  const handleChange = async (next: HilMode) => {
    try {
      await setMode(next);
    } catch {
      toast.error("Failed to update approval mode");
    }
  };

  return (
    <SettingsSection
      title="Approvals"
      titleAccessory={
        <Chip size="sm" variant="flat" color="success">
          Beta
        </Chip>
      }
      description={APPROVALS_SECTION_DESCRIPTION}
    >
      <SettingsRow
        label="Approval mode"
        description={
          APPROVAL_MODES.find((option) => option.mode === mode)?.description
        }
      >
        <Select
          size="sm"
          className="w-48"
          aria-label="Approval mode"
          selectedKeys={[mode]}
          isDisabled={isLoading || isSavingMode}
          onSelectionChange={(keys) => {
            const next = Array.from(keys)[0] as HilMode | undefined;
            if (next && next !== mode) handleChange(next);
          }}
        >
          {APPROVAL_MODES.map((option) => (
            <SelectItem key={option.mode}>{option.label}</SelectItem>
          ))}
        </Select>
      </SettingsRow>
      <SettingsRow label={ALWAYS_ASKS_LABEL} description={ALWAYS_ASKS_NOTE} />
      <SettingsRow
        label="Per-tool approvals"
        description="Force a specific tool to always ask, in each integration's tool list."
      >
        <Button
          size="sm"
          variant="flat"
          className="rounded-xl"
          onPress={() => router.push("/integrations")}
        >
          Open Integrations
        </Button>
      </SettingsRow>
    </SettingsSection>
  );
}
