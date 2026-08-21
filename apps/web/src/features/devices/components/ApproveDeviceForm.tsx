"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { CheckmarkCircle02Icon, ComputerIcon } from "@icons";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import { devicesApi } from "../api/devicesApi";
import { BRIDGE_UP_COMMAND, PAIRING_CODE_PLACEHOLDER } from "../constants";
import { DeviceSetupGuide } from "./DeviceSetupGuide";

export function ApproveDeviceForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const prefilledCode = searchParams.get("code") ?? "";
  const [code, setCode] = useState(prefilledCode);
  const [isApproving, setIsApproving] = useState(false);
  const [approved, setApproved] = useState<string | null>(null);

  // The CLI links here with the code already in the URL, so that visitor has
  // finished the setup steps by definition — only show the guide to someone who
  // arrived from Settings and may not have run anything yet.
  const cameFromCli = Boolean(prefilledCode);

  const approve = async () => {
    const trimmed = code.trim();
    if (!trimmed) {
      toast.error("Enter the code shown in your terminal");
      return;
    }
    setIsApproving(true);
    try {
      const result = await devicesApi.approve(trimmed);
      setApproved(result.name);
      trackEvent(ANALYTICS_EVENTS.DEVICE_CONNECTED, {
        source: cameFromCli ? "cli" : "settings",
      });
    } catch {
      // apiService already surfaced the error toast
    } finally {
      setIsApproving(false);
    }
  };

  if (approved) {
    return (
      <div className="flex flex-col items-center gap-4 rounded-2xl bg-zinc-800 p-8 text-center">
        <CheckmarkCircle02Icon className="size-10 text-success" />
        <div>
          <h2 className="text-lg font-medium">Device paired</h2>
          <p className="text-sm text-zinc-400">
            &ldquo;{approved}&rdquo; is now linked. Head back to your terminal
            to finish choosing what it exposes, then run{" "}
            <span className="font-mono">{BRIDGE_UP_COMMAND}</span> to connect.
          </p>
        </div>
        <Button variant="flat" onPress={() => router.push("/settings/devices")}>
          Manage devices
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 rounded-2xl bg-zinc-800 p-8">
      <div className="flex items-center gap-3">
        <ComputerIcon className="size-6 shrink-0 text-zinc-400" />
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-medium">Add a device</h2>
            <Chip size="sm" variant="flat" color="success">
              Beta
            </Chip>
          </div>
          <p className="text-sm text-zinc-400">
            {cameFromCli
              ? "Confirm the code from your terminal to link this machine to your account."
              : "Connect a machine so GAIA can reach its local MCP servers and files."}
          </p>
        </div>
      </div>

      {!cameFromCli && <DeviceSetupGuide />}

      <div className="flex flex-col gap-4">
        <Input
          label="Pairing code"
          value={code}
          onValueChange={setCode}
          placeholder={PAIRING_CODE_PLACEHOLDER}
          autoFocus
        />
        <Button color="primary" isLoading={isApproving} onPress={approve}>
          Approve device
        </Button>
      </div>
    </div>
  );
}
