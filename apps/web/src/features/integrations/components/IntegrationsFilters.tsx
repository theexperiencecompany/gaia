"use client";

import { Input } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { Tab, Tabs } from "@heroui/tabs";
import { SearchIcon } from "@icons";
import { useCallback, useEffect, useRef, useState } from "react";

const CATEGORIES = [
  { key: "all", label: "All" },
  { key: "productivity", label: "Productivity" },
  { key: "communication", label: "Communication" },
  { key: "developer", label: "Developer" },
  { key: "analytics", label: "Analytics" },
  { key: "finance", label: "Finance" },
  { key: "ai-ml", label: "AI & ML" },
  { key: "education", label: "Education" },
  { key: "personal", label: "Personal" },
  { key: "capabilities", label: "Capabilities" },
  { key: "other", label: "Other" },
];

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
  initialFilters?: {
    search?: string;
    category?: string;
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
  initialFilters = {},
}) => {
  const [search, setSearch] = useState(initialFilters.search || "");
  const [category, setCategory] = useState(initialFilters.category || "all");
  const [sort, setSort] = useState(initialFilters.sort || "popular");

  const debouncedSearch = useDebouncedCallback((value: string) => {
    onFilterChange({ search: value, category, sort });
  }, 300);

  const handleSearchChange = (value: string) => {
    setSearch(value);
    debouncedSearch(value);
  };

  const handleCategoryChange = (key: string) => {
    setCategory(key);
    onFilterChange({ search, category: key, sort });
  };

  const handleSortChange = (key: string) => {
    setSort(key);
    onFilterChange({ search, category, sort: key });
  };

  return (
    <div className="mb-8 space-y-4">
      <div className="grid grid-cols-7 items-center justify-between gap-5">
        <Tabs
          className="col-span-4"
          selectedKey={category}
          onSelectionChange={(key) => handleCategoryChange(key as string)}
          variant="light"
        >
          {CATEGORIES.map((cat) => (
            <Tab key={cat.key} title={cat.label} />
          ))}
        </Tabs>

        <div className="flex justify-center pl-3">
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
        </div>

        <Input
          className="col-span-2"
          type="search"
          placeholder="Search integrations..."
          value={search}
          onValueChange={handleSearchChange}
          startContent={<SearchIcon className="text-zinc-400" />}
        />
      </div>
    </div>
  );
};
