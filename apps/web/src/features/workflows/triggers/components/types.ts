/**
 * Shared types for trigger UI components
 */

export interface OptionItem {
  value: string;
  label: string;
}

export interface TriggerConnectionPromptProps {
  integrationName: string;
  integrationId: string;
  iconUrl?: string | null;
  onConnect: () => void;
}

export interface TriggerTagInputProps {
  /** Visible label. Omit when a parent row already provides one. */
  label?: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  emptyPlaceholder?: string;
  /** Static prefix shown inside the input (e.g. "github.com/"). */
  prefix?: string;
  validate?: (value: string) => boolean;
  formatTag?: (value: string) => string;
  description?: React.ReactNode;
}

export interface TriggerSelectToggleProps {
  label: string;
  selectProps: {
    options: OptionItem[];
    selectedValues: string[];
    onSelectionChange: (values: string[]) => void;
    isLoading?: boolean;
    placeholder?: string;
    renderValue?: (items: { key: string; textValue: string }[]) => string;
    description?: React.ReactNode;
  };
  tagInputProps: {
    values: string[];
    onChange: (values: string[]) => void;
    placeholder?: string;
    emptyPlaceholder?: string;
    validate?: (value: string) => boolean;
    formatTag?: (value: string) => string;
  };
  searchConfig?: {
    enabled: boolean;
    searchValue: string;
    onSearchChange: (value: string) => void;
    placeholder?: string;
  };
  allowManualInput?: boolean;
}
