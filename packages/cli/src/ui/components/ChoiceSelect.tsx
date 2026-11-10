/**
 * @inkjs/ui's Select over a closed set of values: the choice arrives as the
 * option's own value type, not a bare string.
 * @module ui/components/ChoiceSelect
 */

import { Select } from "@inkjs/ui";
import type React from "react";

export interface Choice<T extends string> {
  label: string;
  value: T;
}

export function ChoiceSelect<T extends string>({
  options,
  onChange,
}: {
  options: readonly Choice<T>[];
  onChange: (value: T) => void;
}): React.ReactElement {
  return (
    <Select
      options={[...options]}
      onChange={(value) => {
        const chosen = options.find((option) => option.value === value);
        if (chosen) onChange(chosen.value);
      }}
    />
  );
}
