"use client";

import { CloseButton, ComboBox, Input, InputGroup } from "@heroui/react";
import { type ReactNode, useContext } from "react";
import { ComboBoxStateContext } from "react-aria-components";

interface ComboBoxInputProps {
  placeholder?: string;
  /** Shown before the typed text, e.g. the selected item's icon or flag. */
  startContent?: ReactNode;
  /** Shown after the typed text, e.g. the selected timezone's offset. */
  endContent?: ReactNode;
  isClearable?: boolean;
  onClear?: () => void;
}

/** The clear (x) button; slot={null} keeps it from becoming a second popover trigger. */
function ComboBoxClearButton({ onClear }: { onClear?: () => void }) {
  const state = useContext(ComboBoxStateContext);
  if (!state?.inputValue) return null;
  return (
    <CloseButton
      slot={null}
      aria-label="Clear"
      onPress={() => {
        state.setSelectedKey(null);
        state.setInputValue("");
        onClear?.();
      }}
    />
  );
}

/** ComboBox's input row with v2 Autocomplete's start and end content and its clear button. */
export function ComboBoxInput({
  placeholder,
  startContent,
  endContent,
  isClearable = false,
  onClear,
}: ComboBoxInputProps) {
  return (
    <ComboBox.InputGroup>
      {startContent ? (
        <InputGroup.Prefix>{startContent}</InputGroup.Prefix>
      ) : null}
      <Input placeholder={placeholder} />
      {endContent ? <InputGroup.Suffix>{endContent}</InputGroup.Suffix> : null}
      {isClearable ? <ComboBoxClearButton onClear={onClear} /> : null}
      <ComboBox.Trigger />
    </ComboBox.InputGroup>
  );
}
