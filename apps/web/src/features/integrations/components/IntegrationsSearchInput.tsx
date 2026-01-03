import { Input } from "@heroui/input";
import { forwardRef } from "react";

import { SearchIcon } from "@/icons";

interface IntegrationsSearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onClear: () => void;
  endContent?: React.ReactNode;
}

export const IntegrationsSearchInput = forwardRef<
  HTMLInputElement,
  IntegrationsSearchInputProps
>(({ value, onChange, endContent }, ref) => {
  return (
    <Input
      ref={ref}
      type="text"
      value={value}
      isClearable={!!value}
      className="max-w-xl"
      radius="full"
      startContent={<SearchIcon width={16} height={16} />}
      endContent={!value ? endContent : undefined}
      onValueChange={onChange}
      placeholder="Search integrations..."
    />
  );
});

IntegrationsSearchInput.displayName = "IntegrationsSearchInput";
