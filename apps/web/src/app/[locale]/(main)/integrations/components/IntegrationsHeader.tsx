"use client";

import { Kbd } from "@heroui/kbd";
import { ConnectIcon } from "@icons";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { IntegrationsSearchInput } from "@/features/integrations/components/IntegrationsSearchInput";

interface IntegrationsHeaderProps {
  searchQuery: string;
  isMac: boolean;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onChange: (value: string) => void;
  onClear: () => void;
  onEnter: () => void;
}

export function IntegrationsHeader({
  searchQuery,
  isMac,
  inputRef,
  onChange,
  onClear,
  onEnter,
}: IntegrationsHeaderProps) {
  return (
    <div className="flex w-full items-center justify-between gap-4 py-1">
      <HeaderTitle
        icon={<ConnectIcon width={20} height={20} />}
        text="Integrations"
      />
      <IntegrationsSearchInput
        ref={inputRef}
        value={searchQuery}
        onChange={onChange}
        onClear={onClear}
        onEnter={onEnter}
        endContent={
          <div className="flex items-center gap-1.5">
            <Kbd keys={[isMac ? "command" : "ctrl"]}>F</Kbd>
          </div>
        }
      />
    </div>
  );
}
