"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { CheckmarkCircle02Icon, ComputerIcon } from "@icons";
import { useState } from "react";
import { devicesApi } from "@/features/devices/api/devicesApi";
import { BRIDGE_UP_COMMAND } from "@/features/devices/constants";
import type { DeviceApprovalRequiredData } from "@/features/devices/types";

interface DeviceApprovalPromptProps {
  device_approval_required: DeviceApprovalRequiredData;
}

export function DeviceApprovalPrompt({
  device_approval_required,
}: DeviceApprovalPromptProps) {
  const { code, message } = device_approval_required;
  const [isApproving, setIsApproving] = useState(false);
  const [approvedName, setApprovedName] = useState<string | null>(null);

  const approve = async () => {
    if (isApproving) return;
    setIsApproving(true);
    try {
      // `code` is the canonical dashed code the backend stored, so it goes to
      // the approve endpoint as-is — no page navigation, the user confirms here.
      const result = await devicesApi.approve(code);
      setApprovedName(result.name);
    } catch {
      // The typed api client already surfaced the error toast.
    } finally {
      setIsApproving(false);
    }
  };

  if (approvedName) {
    return (
      <div className="w-fit max-w-md rounded-2xl bg-zinc-800 p-4 text-white">
        <div className="flex items-start gap-3">
          <CheckmarkCircle02Icon
            width={22}
            height={22}
            className="shrink-0 text-success"
          />
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-sm font-medium">Device linked</span>
            <p className="text-xs font-light text-zinc-400">
              &ldquo;{approvedName}&rdquo; is connected to your account. Run{" "}
              <span className="font-mono text-zinc-300">
                {BRIDGE_UP_COMMAND}
              </span>{" "}
              on it to bring it online.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-fit max-w-md rounded-2xl bg-zinc-800 p-4 text-white">
      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-3">
          <div className="shrink-0 pt-0.5">
            <ComputerIcon width={22} height={22} className="text-primary" />
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="text-sm font-medium">Approve this device</span>
            <p className="text-xs font-light text-zinc-400">{message}</p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-900 p-3">
          <Chip variant="flat" color="primary" className="font-mono">
            {code}
          </Chip>
          <Button
            color="primary"
            size="sm"
            isLoading={isApproving}
            onPress={approve}
          >
            Approve
          </Button>
        </div>
      </div>
    </div>
  );
}
