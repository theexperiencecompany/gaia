"use client";

import { useRef } from "react";

import { UseCase, useCasesData } from "../constants/dummy-data";
import UseCaseCard from "./UseCaseCard";

interface SimilarUseCasesProps {
  currentSlug: string;
  currentCategories: string[];
}

export default function SimilarUseCases({
  currentSlug,
  currentCategories,
}: SimilarUseCasesProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const getSimilarUseCases = (): UseCase[] => {
    const similarCases = useCasesData
      .filter((useCase) => {
        if (useCase.slug === currentSlug) return false;

        const hasCommonCategory = useCase.categories.some((cat) =>
          currentCategories.includes(cat),
        );
        return hasCommonCategory;
      })
      .slice(0, 6);

    if (similarCases.length < 3) {
      const randomCases = useCasesData
        .filter((useCase) => useCase.slug !== currentSlug)
        .sort(() => Math.random() - 0.5)
        .slice(0, 6 - similarCases.length);

      return [...similarCases, ...randomCases];
    }

    return similarCases;
  };

  const similarUseCases = getSimilarUseCases();

  if (similarUseCases.length === 0) return null;

  return (
    <div className="space-y-6">
      <h2 className="text-center font-serif text-5xl font-light text-foreground">
        You Might Also Like
      </h2>

      <div
        ref={scrollContainerRef}
        className="no-scrollbar flex gap-4 overflow-x-auto pb-4"
        style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}
      >
        {similarUseCases.map((useCase) => (
          <div key={useCase.slug} className="w-[350px] shrink-0">
            <UseCaseCard
              title={useCase.title}
              description={useCase.description}
              action_type={useCase.action_type}
              integrations={useCase.integrations}
              prompt={useCase.prompt}
              slug={useCase.slug}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
