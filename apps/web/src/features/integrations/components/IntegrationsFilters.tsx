"use client";

import { Chip, InputGroup, ListBox, Select, TextField } from "@heroui/react";
import { SearchIcon } from "@icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { toneVariants } from "@/components/shared/tone";
import { INTEGRATION_CATEGORIES } from "@/features/integrations/constants/categories";
import { cn } from "@/lib/utils";

const SORT_OPTIONS = [
  { key: "popular", label: "Most Popular" },
  { key: "recent", label: "Most Recent" },
  { key: "name", label: "Name (A-Z)" },
];

interface IntegrationsFiltersProps {
  onFilterChange: (filters: {
    search?: string;
    category?: string;
    sort?: string;
  }) => void;
  /** Controlled by the parent so external controls (featured banners) stay in sync. */
  category: string;
  initialFilters?: {
    search?: string;
    sort?: string;
  };
}

/**
 * Custom debounce hook since use-debounce is not installed
 */
function useDebouncedCallback<T extends (...args: Parameters<T>) => void>(
  callback: T,
  delay: number,
): T {
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const callbackRef = useRef(callback);

  // Update callback ref when callback changes
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return useCallback(
    ((...args: Parameters<T>) => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = setTimeout(() => {
        callbackRef.current(...args);
      }, delay);
    }) as T,
    [delay],
  );
}

export const IntegrationsFilters: React.FC<IntegrationsFiltersProps> = ({
  onFilterChange,
  category,
  initialFilters = {},
}) => {
  const [search, setSearch] = useState(initialFilters.search || "");
  const [sort, setSort] = useState(initialFilters.sort || "popular");

  // Deep links (?search=&category=) need no sync here: the parent hydrates its
  // filter state via useSearchParams() and passes it down as `category` +
  // `initialFilters`, so this component starts in sync without an effect.

  const debouncedSearch = useDebouncedCallback((value: string) => {
    onFilterChange({ search: value, category, sort });
  }, 300);

  const handleSearchChange = (value: string) => {
    setSearch(value);
    debouncedSearch(value);
  };

  const handleCategoryChange = (key: string) => {
    onFilterChange({ search, category: key, sort });
  };

  const handleSortChange = (key: string) => {
    setSort(key);
    onFilterChange({ search, category, sort: key });
  };

  return (
    <div className="mb-8 space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-5">
        <div className="flex flex-1 min-w-0 flex-wrap items-center gap-2">
          {INTEGRATION_CATEGORIES.map((cat) => (
            <Chip
              key={cat.key}
              variant={category === cat.key ? "primary" : "soft"}
              color={category === cat.key ? "accent" : "default"}
              size="lg"
              className={cn(
                "cursor-pointer font-light! backdrop-blur-2xl!",
                category !== cat.key &&
                  `bg-white/5! ${toneVariants({ tone: "muted" })}`,
              )}
              onClick={() => handleCategoryChange(cat.key)}
            >
              {cat.label}
            </Chip>
          ))}
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <Select
            selectedKey={sort}
            onSelectionChange={(key) => {
              if (typeof key === "string") handleSortChange(key);
            }}
            className={fieldVariants({
              labelPlacement: "inside",
              className: "w-40",
            })}
            aria-label="Sort by"
          >
            <Select.Trigger>
              <GaiaSelectValue />
              <Select.Indicator />
            </Select.Trigger>
            <Select.Popover>
              <ListBox>
                {SORT_OPTIONS.map((option) => (
                  <ListBox.Item
                    key={option.key}
                    id={option.key}
                    textValue={option.label}
                  >
                    {option.label}
                  </ListBox.Item>
                ))}
              </ListBox>
            </Select.Popover>
          </Select>

          <TextField
            className="flex-1 sm:w-72 sm:flex-none min-w-0"
            aria-label="Search integrations"
            value={search}
            onChange={handleSearchChange}
          >
            <InputGroup>
              <InputGroup.Prefix>
                <SearchIcon className="text-zinc-400" />
              </InputGroup.Prefix>
              <InputGroup.Input
                type="search"
                placeholder="Search integrations..."
              />
            </InputGroup>
          </TextField>
        </div>
      </div>
    </div>
  );
};
