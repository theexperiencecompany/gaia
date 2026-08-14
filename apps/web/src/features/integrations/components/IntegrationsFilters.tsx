"use client";

import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { SearchIcon } from "@icons";
import { useCallback, useEffect, useRef, useState } from "react";
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
  const hasSyncedParams = useRef(false);

  useEffect(() => {
    if (hasSyncedParams.current) return;
    const params = new URLSearchParams(window.location.search);
    const urlSearch = params.get("search");
    const urlCategory = params.get("category");
    if (urlSearch || urlCategory) {
      hasSyncedParams.current = true;
      if (urlSearch) setSearch(urlSearch);
      onFilterChange({
        search: urlSearch || search,
        category: urlCategory || category,
        sort,
      });
    }
  }, []);

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
              variant={category === cat.key ? "solid" : "flat"}
              color={category === cat.key ? "primary" : "default"}
              size="lg"
              className={cn(
                "cursor-pointer font-light! backdrop-blur-2xl!",
                category !== cat.key && "bg-white/5! text-foreground-500",
              )}
              onClick={() => handleCategoryChange(cat.key)}
            >
              {cat.label}
            </Chip>
          ))}
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <Select
            selectedKeys={[sort]}
            onSelectionChange={(keys) => {
              const selected = Array.from(keys)[0] as string;
              if (selected) handleSortChange(selected);
            }}
            className="w-40"
            aria-label="Sort by"
          >
            {SORT_OPTIONS.map((option) => (
              <SelectItem key={option.key}>{option.label}</SelectItem>
            ))}
          </Select>

          <Input
            className="flex-1 sm:w-72 sm:flex-none min-w-0"
            type="search"
            placeholder="Search integrations..."
            value={search}
            onValueChange={handleSearchChange}
            startContent={<SearchIcon className="text-zinc-400" />}
          />
        </div>
      </div>
    </div>
  );
};
