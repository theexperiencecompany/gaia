"use client";

import type React from "react";

interface ShowcaseSidebarContentProps {
  sidebarIcon: React.ReactNode;
  sidebarTitle: string;
  contentSections: Array<{ title: string; description: string }>;
}

export default function ShowcaseSidebarContent({
  sidebarIcon,
  sidebarTitle,
  contentSections,
}: ShowcaseSidebarContentProps) {
  return (
    <>
      <div className="flex items-center text-3xl font-serif gap-2 text-primary">
        {sidebarIcon} {sidebarTitle}
      </div>
      {contentSections.map((section) => (
        <div key={section.title}>
          <h3 className="mb-2 text-xl font-medium text-zinc-100">
            {section.title}
          </h3>
          <p className="text-base font-light text-zinc-400 text-left">
            {section.description}
          </p>
        </div>
      ))}
    </>
  );
}
