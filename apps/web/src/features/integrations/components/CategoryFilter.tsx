"use client";

import { Chip } from "@heroui/react";
import { getCategoryLabel } from "../constants/categories";

interface CategoryFilterProps {
  categories: string[];
  selectedCategory: string;
  onCategoryChange: (category: string) => void;
}

export function CategoryFilter({
  categories,
  selectedCategory,
  onCategoryChange,
}: CategoryFilterProps) {
  // Add "all" as the first option
  const allCategories = ["all", ...categories];

  return (
    <div className="flex flex-wrap gap-2">
      {allCategories.map((category) => (
        <Chip
          key={category}
          variant={selectedCategory === category ? "primary" : "soft"}
          color={selectedCategory === category ? "accent" : "default"}
          className="cursor-pointer transition-colors duration-200"
          onClick={() => onCategoryChange(category)}
        >
          {getCategoryLabel(category)}
        </Chip>
      ))}
    </div>
  );
}
