"use client";

import { Chip, ListBox, Select } from "@heroui/react";
import type { HilMode } from "@shared/chat";
import { useRouter } from "next/navigation";
import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useHilPreferences } from "@/features/settings/hooks/useHilPreferences";
import { toast } from "@/lib/toast";

const MODES: { key: HilMode; label: string; description: string }[] = [
  {
    key: "always_allow",
    label: "Allow always",
    description: "Never ask. Run every action.",
  },
  {
    key: "always_ask",
    label: "Always ask",
    description: "Approve before GAIA sends, deletes, or posts.",
  },
  {
    key: "auto",
    label: "Auto",
    description: "Run what you asked for; ask when it's unclear.",
  },
];

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
        <Chip size="sm" variant="soft" color="success">
          Beta
        </Chip>
      }
      description="Choose when GAIA checks with you before destructive actions."
    >
      <SettingsRow
        label="Approval mode"
        description={MODES.find((m) => m.key === mode)?.description}
      >
        <Select
          className={inputVariants({ size: "sm", className: "w-48" })}
          aria-label="Approval mode"
          value={mode}
          isDisabled={isLoading || isSavingMode}
          onChange={(key) => {
            const next = key as HilMode | null;
            if (next && next !== mode) handleChange(next);
          }}
        >
          <Select.Trigger>
            <GaiaSelectValue />
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover>
            <ListBox>
              {MODES.map((m) => (
                <GaiaListBoxItem key={m.key} id={m.key} textValue={m.label} />
              ))}
            </ListBox>
          </Select.Popover>
        </Select>
      </SettingsRow>
      <SettingsRow
        label="Per-tool approvals"
        description="Force a specific tool to always ask, in each integration's tool list."
      >
        <GaiaButton
          size="sm"
          shape="md"
          variant="default-soft"
          onPress={() => router.push("/integrations")}
        >
          Open Integrations
        </GaiaButton>
      </SettingsRow>
    </SettingsSection>
  );
}
