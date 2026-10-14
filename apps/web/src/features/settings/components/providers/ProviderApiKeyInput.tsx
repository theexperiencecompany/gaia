"use client";

import { Input, type InputProps } from "@heroui/input";
import { Link } from "@heroui/link";
import { SquareArrowUpRight02Icon } from "@icons";
import { useState } from "react";
import { VisibilityToggleButton } from "@/components/shared/VisibilityToggleButton";
import {
  type CredentialProvider,
  PROVIDER_KEY_URLS,
} from "@/features/settings/api/providersApi";

interface ProviderApiKeyInputProps
  extends Omit<InputProps, "type" | "label" | "endContent"> {
  provider: CredentialProvider;
}

/** A provider's API key field: masked with a reveal toggle, plus a link to
 * where the key is issued when the provider has one. */
export function ProviderApiKeyInput({
  provider,
  ...inputProps
}: ProviderApiKeyInputProps) {
  const [isVisible, setIsVisible] = useState(false);
  const keyUrl = PROVIDER_KEY_URLS[provider];

  return (
    <>
      <Input
        {...inputProps}
        type={isVisible ? "text" : "password"}
        label="API key"
        endContent={
          <VisibilityToggleButton
            visible={isVisible}
            onToggle={() => setIsVisible((visible) => !visible)}
            subject="API key"
          />
        }
      />
      {keyUrl && (
        <Link
          href={keyUrl}
          isExternal
          size="sm"
          className="inline-flex items-center gap-1 text-xs text-zinc-500"
        >
          Get your key
          <SquareArrowUpRight02Icon size={12} />
        </Link>
      )}
    </>
  );
}
