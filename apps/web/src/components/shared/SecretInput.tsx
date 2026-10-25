"use client";

import { Button } from "@heroui/button";
import { Input, type InputProps } from "@heroui/input";
import { ViewIcon, ViewOffSlashIcon } from "@icons";
import { useState } from "react";

interface SecretInputProps extends Omit<InputProps, "type" | "endContent"> {
  /** What the toggle reveals, for its aria-label ("password", "API key"). */
  subject: string;
  /** Controlled reveal state, for one toggle that reveals several fields. */
  isRevealed?: boolean;
  onRevealedChange?: (isRevealed: boolean) => void;
}

/** A masked input with a show/hide toggle in its end content. */
export function SecretInput({
  subject,
  isRevealed: controlledRevealed,
  onRevealedChange,
  ...inputProps
}: SecretInputProps) {
  const [ownRevealed, setOwnRevealed] = useState(false);
  const isRevealed = controlledRevealed ?? ownRevealed;
  const toggle = () => {
    setOwnRevealed(!isRevealed);
    onRevealedChange?.(!isRevealed);
  };

  return (
    <Input
      {...inputProps}
      type={isRevealed ? "text" : "password"}
      endContent={
        <Button
          isIconOnly
          size="sm"
          variant="light"
          radius="full"
          aria-label={`${isRevealed ? "Hide" : "Show"} ${subject}`}
          onPress={toggle}
          className="text-zinc-500"
        >
          {isRevealed ? <ViewOffSlashIcon size={16} /> : <ViewIcon size={16} />}
        </Button>
      }
    />
  );
}
