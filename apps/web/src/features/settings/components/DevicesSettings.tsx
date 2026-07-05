"use client";

import { Button } from "@heroui/button";
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
          <h2 className="text-lg font-medium">Devices</h2>
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
          startContent={<PlusSignIcon className="size-4" />}
          onPress={() => router.push("/devices/approve")}
        >
          Add device
        </Button>
      </div>
      <DevicesManager />
    </SettingsPage>
  );
}
