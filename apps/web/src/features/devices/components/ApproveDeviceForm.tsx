"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { CheckmarkCircle02Icon, ComputerIcon } from "@icons";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "@/lib/toast";
import { devicesApi } from "../api/devicesApi";

export function ApproveDeviceForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [code, setCode] = useState(searchParams.get("code") ?? "");
  const [isApproving, setIsApproving] = useState(false);
  const [approved, setApproved] = useState<string | null>(null);

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
            to finish setup.
          </p>
        </div>
        <Button variant="flat" onPress={() => router.push("/settings/devices")}>
          Manage devices
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 rounded-2xl bg-zinc-800 p-8">
      <div className="flex items-center gap-3">
        <ComputerIcon className="size-6 text-zinc-400" />
        <div>
          <h2 className="text-lg font-medium">Approve a device</h2>
          <p className="text-sm text-zinc-400">
            Enter the code shown in your terminal to link this machine to your
            account.
          </p>
        </div>
      </div>
      <Input
        label="Pairing code"
        value={code}
        onValueChange={setCode}
        placeholder="XXXX-XXXX"
        autoFocus
      />
      <Button color="primary" isLoading={isApproving} onPress={approve}>
        Approve device
      </Button>
    </div>
  );
}
