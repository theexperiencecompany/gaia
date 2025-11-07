import { Input } from "@heroui/input";
import { Search, X } from "lucide-react";
import React from "react";

interface IntegrationsSearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onClear: () => void;
}

export const IntegrationsSearchInput: React.FC<
  IntegrationsSearchInputProps
> = ({ value, onChange, onClear }) => {
  return (
    <div className="relative w-full">
      <Search className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-zinc-400" />
      <Input
        type="text"
        value={value}
        isClearable
        radius="full"
        startContent={<Search width={16} height={16} />}
        onValueChange={onChange}
        placeholder="Search integrations..."
      />
    </div>
  );
};
