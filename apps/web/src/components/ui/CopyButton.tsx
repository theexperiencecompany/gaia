"use client";

import type { ButtonProps } from "@heroui/react";
import { CheckmarkCircle01Icon, Copy01Icon } from "@icons";
import { useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { copyWithFeedback } from "@/lib/clipboard";

interface CopyButtonProps {
  textToCopy: string;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  className?: string;
  copied?: boolean; // Optional external copied state
  onCopy?: () => void; // Optional external copy handler
}

export default function CopyButton({
  textToCopy,
  variant = "secondary",
  size = "sm",
  className = "",
  copied: externalCopied,
  onCopy,
}: CopyButtonProps) {
  const [internalCopied, setInternalCopied] = useState(false);

  // Use external copied state if provided, otherwise use internal
  const copied = externalCopied !== undefined ? externalCopied : internalCopied;

  const handleCopy = async () => {
    if (onCopy) {
      // If external handler provided, use it
      onCopy();
    } else {
      // Otherwise use internal logic
      if (!(await copyWithFeedback(textToCopy))) return;
      setInternalCopied(true);
      setTimeout(() => setInternalCopied(false), 2000);
    }
  };

  return (
    <GaiaButton
      isIconOnly
      variant={variant}
      size={size}
      onPress={handleCopy}
      className={className}
      aria-label={copied ? "Copied" : "Copy to clipboard"}
    >
      {copied ? (
        <CheckmarkCircle01Icon className="h-4 w-4" />
      ) : (
        <Copy01Icon className="h-4 w-4" />
      )}
    </GaiaButton>
  );
}
