"use client";

import { Button } from "@heroui/button";
import { CheckmarkCircle01Icon, Copy01Icon } from "@icons";
import { useState } from "react";

interface CopyButtonProps {
  textToCopy: string;
  variant?: "solid" | "flat" | "ghost" | "bordered";
  size?: "sm" | "md" | "lg";
  className?: string;
  copied?: boolean; // Optional external copied state
  onCopy?: () => void; // Optional external copy handler
}

export default function CopyButton({
  textToCopy,
  variant = "flat",
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
      try {
        await navigator.clipboard.writeText(textToCopy);
        setInternalCopied(true);
        setTimeout(() => setInternalCopied(false), 2000);
      } catch (err) {
        console.error("Failed to copy text:", err);
      }
    }
  };

  return (
    <Button
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
    </Button>
  );
}
