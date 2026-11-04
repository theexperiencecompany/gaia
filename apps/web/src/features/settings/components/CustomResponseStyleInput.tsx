"use client";

import { Input, TextField } from "@heroui/react";

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
          className="min-h-[36px] rounded-lg bg-zinc-800/50 px-3 text-sm hover:bg-zinc-700/50"
        />
      </TextField>
    </div>
  );
}
