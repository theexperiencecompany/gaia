"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Select, SelectItem } from "@heroui/select";
import type { HilMode } from "@shared/chat";
import { useRouter } from "next/navigation";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useHilPreferences } from "@/features/settings/hooks/useHilPreferences";
import { toast } from "@/lib/toast";

const MODES: { key: HilMode; label: string; description: string }[] = [
  {
    key: "always_allow",
    label: "Allow always",
    description: "Never ask — run every action.",
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
        <Chip size="sm" variant="flat" color="success">
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
          {MODES.map((m) => (
            <SelectItem key={m.key}>{m.label}</SelectItem>
          ))}
        </Select>
      </SettingsRow>
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
