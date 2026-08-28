"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { CheckmarkCircle02Icon, ComputerIcon } from "@icons";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import { devicesApi } from "../api/devicesApi";
import {
  BRIDGE_UP_COMMAND,
  PAIRING_CODE_GROUP_LENGTH,
  PAIRING_CODE_LENGTH,
  PAIRING_CODE_SEPARATOR,
} from "../constants";
import { DeviceSetupGuide } from "./DeviceSetupGuide";
import { PairingCodeInput } from "./PairingCodeInput";

/** The input holds the code without its separator; the API expects it back in. */
function toApiCode(digits: string): string {
  return `${digits.slice(0, PAIRING_CODE_GROUP_LENGTH)}${PAIRING_CODE_SEPARATOR}${digits.slice(PAIRING_CODE_GROUP_LENGTH)}`;
}

function toInputCode(code: string): string {
  return code
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, PAIRING_CODE_LENGTH);
}

export function ApproveDeviceForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const prefilledCode = searchParams.get("code") ?? "";
  const [code, setCode] = useState(() => toInputCode(prefilledCode));
  const [isApproving, setIsApproving] = useState(false);
  const [approved, setApproved] = useState<string | null>(null);

  // The CLI links here with the code already in the URL, so that visitor has
  // finished the setup steps by definition — only show the guide to someone who
  // arrived from Settings and may not have run anything yet.
  const cameFromCli = Boolean(prefilledCode);

  const approve = async (digits: string) => {
    if (digits.length < PAIRING_CODE_LENGTH) {
      toast.error("Enter the code shown in your terminal");
      return;
    }
    if (isApproving) return;
    setIsApproving(true);
    try {
      const result = await devicesApi.approve(toApiCode(digits));
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
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-medium">Device paired</h2>
          <p className="text-pretty text-sm text-zinc-400">
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
    <div className="flex flex-col rounded-2xl bg-zinc-800 p-6">
      <header className="flex gap-3.5 pb-5">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-zinc-900">
          <ComputerIcon className="size-5 text-zinc-300" />
        </div>
        <div className="flex flex-col gap-1 pt-0.5">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-medium leading-none">Add a device</h2>
            <Chip size="sm" variant="flat" color="success">
              Beta
            </Chip>
          </div>
          <p className="text-pretty text-sm text-zinc-400">
            {cameFromCli
              ? "Confirm the code from your terminal to link this machine to your account."
              : "Connect a machine so GAIA can reach its local MCP servers and files."}
          </p>
        </div>
      </header>

      <Divider className="bg-zinc-700/50" />

      {!cameFromCli && (
        <>
          <div className="py-5">
            <DeviceSetupGuide />
          </div>
          <Divider className="bg-zinc-700/50" />
        </>
      )}

      <div className="flex flex-col gap-3 pt-5">
        <label
          htmlFor="pairing-code"
          className="text-sm font-medium text-zinc-100"
        >
          Pairing code
        </label>
        <PairingCodeInput
          value={code}
          onChange={setCode}
          onComplete={approve}
          isDisabled={isApproving}
        />
        <Button
          color="primary"
          isLoading={isApproving}
          isDisabled={code.length < PAIRING_CODE_LENGTH}
          onPress={() => approve(code)}
        >
          Approve device
        </Button>
      </div>
    </div>
  );
}
