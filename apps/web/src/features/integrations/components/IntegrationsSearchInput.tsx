import { Input } from "@heroui/input";
import type React from "react";

import { SearchIcon } from "@/icons";

interface IntegrationsSearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onClear: () => void;
}

export const IntegrationsSearchInput: React.FC<
  IntegrationsSearchInputProps
> = ({ value, onChange }) => {
  return (
    <Input
      type="text"
      value={value}
      isClearable
      className="max-w-xl"
      radius="full"
      startContent={<SearchIcon width={16} height={16} />}
      onValueChange={onChange}
      placeholder="Search integrations..."
    />
  );
};
