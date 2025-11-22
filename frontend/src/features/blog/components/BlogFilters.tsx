"use client";

import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { useCallback, useMemo, useState } from "react";

import { SearchIcon } from '@/icons';
import type { BlogPost } from "@/lib/blog";

interface BlogFiltersProps {
  blogs: BlogPost[];
  onFilterChange: (filteredBlogs: BlogPost[]) => void;
}

export function BlogFilters({ blogs, onFilterChange }: BlogFiltersProps) {
  const [selectedCategory, setSelectedCategory] = useState<string>("All");
  const [searchQuery, setSearchQuery] = useState("");

  const categories = useMemo(() => {
    const categoryCounts = blogs.reduce(
      (acc, blog) => {
        acc[blog.category] = (acc[blog.category] || 0) + 1;
        return acc;
      },
      {} as Record<string, number>,
    );

    const sortedCategories = Object.entries(categoryCounts)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 5)
      .map(([category]) => category);

    return ["All", ...sortedCategories];
  }, [blogs]);

  const filterBlogs = useCallback(
    (category: string, query: string) => {
      let filtered = blogs;

      if (category !== "All") {
        filtered = filtered.filter((blog) => blog.category === category);
      }

      if (query.trim()) {
        const lowerQuery = query.toLowerCase();
        filtered = filtered.filter(
          (blog) =>
            blog.title.toLowerCase().includes(lowerQuery) ||
            blog.category.toLowerCase().includes(lowerQuery) ||
            blog.authors.some((author) =>
              author.name.toLowerCase().includes(lowerQuery),
            ),
        );
      }

      onFilterChange(filtered);
    },
    [blogs, onFilterChange],
  );

  const handleCategoryChange = (category: string) => {
    setSelectedCategory(category);
    filterBlogs(category, searchQuery);
  };

  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    filterBlogs(selectedCategory, value);
  };

  return (
    <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
      <div className="flex flex-wrap">
        {categories.map((category) => (
          <Chip
            key={category}
            variant="light"
            className="cursor-pointer"
            size="lg"
            color={selectedCategory === category ? "primary" : "default"}
            onClick={() => handleCategoryChange(category)}
          >
            {category}
          </Chip>
        ))}
      </div>

      <Input
        type="text"
        placeholder="SearchIcon posts..."
        value={searchQuery}
        onValueChange={handleSearchChange}
        startContent={<SearchIcon className="size-5 text-default-400" />}
        variant="flat"
        radius="full"
        className="w-full max-w-sm"
      />
    </div>
  );
}
