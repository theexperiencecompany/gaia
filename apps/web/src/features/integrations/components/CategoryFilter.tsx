"use client";

import { Chip } from "@heroui/chip";
import {
  INTEGRATION_CATEGORIES,
  type IntegrationCategoryId,
} from "../constants/categories";

interface CategoryFilterProps {
  selectedCategory: IntegrationCategoryId;
  onCategoryChange: (category: IntegrationCategoryId) => void;
}

export function CategoryFilter({
  selectedCategory,
  onCategoryChange,
}: CategoryFilterProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {INTEGRATION_CATEGORIES.map((category) => (
        <Chip
          key={category.id}
          variant={selectedCategory === category.id ? "solid" : "flat"}
          color={selectedCategory === category.id ? "primary" : "default"}
          className="cursor-pointer transition-all duration-200"
          onClick={() => onCategoryChange(category.id)}
        >
          {category.label}
        </Chip>
      ))}
    </div>
  );
}
