"use client";

import { Button, Description, Input, Label, TextField } from "@heroui/react";
import { CloudIcon } from "@icons";
import { type FormEvent, useState } from "react";
import { FormError } from "@/components/shared/FormError";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
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
        <TextField
          className={fieldVariants({ labelPlacement: "inside" })}
          value={address}
          onChange={setAddress}
          isRequired
          isDisabled={isConnecting}
        >
          <Label>Server address</Label>
          <Input
            type="text"
            placeholder="https://gaia.example.com"
            autoComplete="url"
          />
          <Description>
            The address you open GAIA at in your browser.
          </Description>
        </TextField>

        {error && <FormError>{error}</FormError>}

        <Button
          type="submit"
          variant="primary"
          isPending={isConnecting}
          className="w-full"
        >
          Connect
        </Button>
      </form>

      {currentOrigin && (
        <GaiaButton
          variant="default-soft"
          isDisabled={isConnecting}
          onPress={() => getElectronAPI()?.switchToGaiaCloud()}
        >
          <CloudIcon height={17} />
          Use GAIA Cloud
        </GaiaButton>
      )}
    </div>
  );
}
