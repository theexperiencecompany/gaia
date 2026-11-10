"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { CloudIcon } from "@icons";
import { type FormEvent, useState } from "react";
import { FormError } from "@/components/shared/FormError";
import { getElectronAPI } from "@/lib/electron/api";

interface SelfHostServerFormProps {
  /** The self-hosted server the app uses now, or null on GAIA Cloud. */
  currentOrigin: string | null;
  /** The current self-hosted server failed to load. */
  unreachable: boolean;
}

/** Point the desktop app at a self-hosted GAIA server; it relaunches on success. */
export function SelfHostServerForm({
  currentOrigin,
  unreachable,
}: SelfHostServerFormProps) {
  const [address, setAddress] = useState(currentOrigin ?? "");
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const api = getElectronAPI();
    if (!api || isConnecting) return;

    setIsConnecting(true);
    setError(null);
    const result = await api.connectSelfHostServer(address);
    // On success the app relaunches against the server; keep the spinner.
    if (result.ok) return;
    setError(result.error);
    setIsConnecting(false);
  }

  return (
    <div className="flex w-full flex-col gap-4">
      {unreachable && currentOrigin && (
        <FormError>
          Couldn&apos;t reach {currentOrigin}. Check that it&apos;s running,
          then connect again.
        </FormError>
      )}

      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <Input
          type="text"
          label="Server address"
          placeholder="https://gaia.example.com"
          description="The address you open GAIA at in your browser."
          value={address}
          onValueChange={setAddress}
          autoComplete="url"
          isRequired
          isDisabled={isConnecting}
        />

        {error && <FormError>{error}</FormError>}

        <Button
          type="submit"
          color="primary"
          isLoading={isConnecting}
          className="w-full"
        >
          Connect
        </Button>
      </form>

      {currentOrigin && (
        <Button
          variant="flat"
          startContent={<CloudIcon height={17} />}
          isDisabled={isConnecting}
          onPress={() => getElectronAPI()?.switchToGaiaCloud()}
        >
          Use GAIA Cloud
        </Button>
      )}
    </div>
  );
}
