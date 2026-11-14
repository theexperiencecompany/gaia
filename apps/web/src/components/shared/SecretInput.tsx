"use client";

import { Description, InputGroup, Label, TextField } from "@heroui/react";
import { ViewIcon, ViewOffSlashIcon } from "@icons";
import { useState } from "react";
import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";

interface SecretInputProps {
  /** What the toggle reveals, for its aria-label ("password", "API key"). */
  subject: string;
  /** The field's label, when it has one. */
  label?: string;
  /** Helper text shown under the field. */
  description?: string;
  placeholder?: string;
  value: string;
  onValueChange: (value: string) => void;
  autoComplete?: string;
  name?: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  /** Controlled reveal state, for one toggle that reveals several fields. */
  isRevealed?: boolean;
  onRevealedChange?: (isRevealed: boolean) => void;
  className?: string;
}

/** A masked input with a show/hide toggle in its end content. */
export function SecretInput({
  subject,
  label,
  description,
  placeholder,
  value,
  onValueChange,
  autoComplete,
  name,
  isRequired,
  isDisabled,
  isRevealed: controlledRevealed,
  onRevealedChange,
  className,
}: SecretInputProps) {
  const [ownRevealed, setOwnRevealed] = useState(false);
  const isRevealed = controlledRevealed ?? ownRevealed;
  const toggle = () => {
    setOwnRevealed(!isRevealed);
    onRevealedChange?.(!isRevealed);
  };

  return (
    <TextField
      className={inputVariants({ size: "sm", className: className })}
      value={value}
      onChange={onValueChange}
      isDisabled={isDisabled}
      isRequired={isRequired}
      name={name}
    >
      {label && <Label>{label}</Label>}
      <InputGroup>
        <InputGroup.Input
          type={isRevealed ? "text" : "password"}
          placeholder={placeholder}
          autoComplete={autoComplete}
        />
        <InputGroup.Suffix>
          <GaiaButton
            shape="pill"
            isIconOnly
            size="sm"
            variant="ghost"
            tone="faint"
            aria-label={`${isRevealed ? "Hide" : "Show"} ${subject}`}
            onPress={toggle}
          >
            {isRevealed ? (
              <ViewOffSlashIcon size={16} />
            ) : (
              <ViewIcon size={16} />
            )}
          </GaiaButton>
        </InputGroup.Suffix>
      </InputGroup>
      {description && <Description>{description}</Description>}
    </TextField>
  );
}
