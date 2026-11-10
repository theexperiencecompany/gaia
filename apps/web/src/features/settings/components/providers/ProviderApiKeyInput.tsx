"use client";

import type { InputProps } from "@heroui/input";
import { Link } from "@heroui/link";
import { SquareArrowUpRight02Icon } from "@icons";
import { SecretInput } from "@/components/shared/SecretInput";

interface ProviderApiKeyInputProps
  extends Omit<InputProps, "type" | "label" | "endContent"> {
  /** The field's name, e.g. "API key" or "API secret". */
  label: string;
  /** Where the provider issues keys; empty when it has no such page. */
  keyUrl: string | null;
}

/** A provider's secret field: masked with a reveal toggle, plus a link to
 * where the key is issued when the provider has one. */
export function ProviderApiKeyInput({
  label,
  keyUrl,
  ...inputProps
}: ProviderApiKeyInputProps) {
  return (
    <>
      <SecretInput {...inputProps} label={label} subject={label} />
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
