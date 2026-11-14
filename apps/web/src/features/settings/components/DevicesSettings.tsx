"use client";

import { Chip } from "@heroui/react";
import { PlusSignIcon } from "@icons";
import { useRouter } from "next/navigation";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { DevicesManager } from "@/features/devices/components/DevicesManager";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";

export default function DevicesSettings() {
  const router = useRouter();

  return (
    <SettingsPage>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-medium">Devices</h2>
            <Chip size="sm" variant="soft" color="success">
              Beta
            </Chip>
          </div>
          <p className="text-sm text-zinc-400">
            Machines connected to GAIA through the gaia bridge daemon. Each
            device can expose local MCP servers and file access. Revoke a device
            to instantly cut its access.
          </p>
        </div>
        <GaiaButton
          variant="accent-soft"
          size="sm"
          className="shrink-0"
          onPress={() => router.push("/settings/devices/approve")}
        >
          <PlusSignIcon className="size-4" />
          Add device
        </GaiaButton>
      </div>
      <DevicesManager />
    </SettingsPage>
  );
}
