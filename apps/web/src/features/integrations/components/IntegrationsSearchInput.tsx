import { Input } from "@heroui/input";
import { forwardRef, type KeyboardEvent } from "react";

import { SearchIcon } from "@/icons";

interface IntegrationsSearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onClear: () => void;
  endContent?: React.ReactNode;
  onEnter?: () => void;
}

export const IntegrationsSearchInput = forwardRef<
  HTMLInputElement,
  IntegrationsSearchInputProps
>(({ value, onChange, endContent, onEnter }, ref) => {
  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && onEnter) {
      e.preventDefault();
      onEnter();
    }
  };

  return (
    <Input
      ref={ref}
      type="text"
      value={value}
      isClearable={!!value}
      className="max-w-lg"
      // radius="full"
      // size="sm"
      startContent={<SearchIcon width={16} height={16} />}
      endContent={!value ? endContent : undefined}
      onValueChange={onChange}
      onKeyDown={handleKeyDown}
      placeholder="Search integrations..."
    />
  );
});

IntegrationsSearchInput.displayName = "IntegrationsSearchInput";
