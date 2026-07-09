"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { PlusSignIcon } from "@icons";
import { useRouter } from "next/navigation";
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
            <Chip size="sm" variant="flat" color="success">
              Beta
            </Chip>
          </div>
          <p className="text-sm text-zinc-400">
            Machines connected to GAIA through the gaia bridge daemon. Each
            device can expose local MCP servers and file access. Revoke a device
            to instantly cut its access.
          </p>
        </div>
        <Button
          size="sm"
          variant="flat"
          color="primary"
          className="shrink-0"
          startContent={<PlusSignIcon className="size-4" />}
          onPress={() => router.push("/settings/devices/approve")}
        >
          Add device
        </Button>
      </div>
      <DevicesManager />
    </SettingsPage>
  );
}
