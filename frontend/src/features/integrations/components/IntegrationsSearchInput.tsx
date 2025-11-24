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
    <div className="relative w-full">
      <SearchIcon className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-zinc-400" />
      <Input
        type="text"
        value={value}
        isClearable
        radius="full"
        startContent={<SearchIcon width={16} height={16} />}
        onValueChange={onChange}
        placeholder="Search integrations..."
      />
    </div>
  );
};
