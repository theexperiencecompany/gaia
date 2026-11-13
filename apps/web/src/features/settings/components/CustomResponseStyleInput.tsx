"use client";

import { Input, TextField } from "@heroui/react";
import { inputVariants } from "@/components/shared/controlVariants";
import { shapeVariants } from "@/components/shared/shape";

interface CustomResponseStyleInputProps {
  value: string;
  onChange: (value: string) => void;
  isDisabled: boolean;
}

export function CustomResponseStyleInput({
  value,
  onChange,
  isDisabled,
}: CustomResponseStyleInputProps) {
  return (
    <div className="space-y-1">
      <TextField isDisabled={isDisabled}>
        <Input
          placeholder="Describe your preferred response style..."
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={inputVariants({
            variant: "translucent",
            className: shapeVariants({
              shape: "sm",
              className: "min-h-[36px] text-sm",
            }),
          })}
        />
      </TextField>
    </div>
  );
}
