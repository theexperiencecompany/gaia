import { InputGroup, TextField } from "@heroui/react";
import { SearchIcon } from "@icons";
import { forwardRef, type KeyboardEvent } from "react";

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
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Enter" && onEnter) {
      e.preventDefault();
      onEnter();
    }
  };

  return (
    <TextField value={value} onChange={onChange} className="max-w-lg">
      <InputGroup>
        <InputGroup.Prefix>
          <SearchIcon width={16} height={16} />
        </InputGroup.Prefix>
        <InputGroup.Input
          ref={ref}
          type="text"
          placeholder="Search integrations..."
          onKeyDown={handleKeyDown}
        />
        {!value && endContent ? (
          <InputGroup.Suffix>{endContent}</InputGroup.Suffix>
        ) : null}
      </InputGroup>
    </TextField>
  );
});

IntegrationsSearchInput.displayName = "IntegrationsSearchInput";
