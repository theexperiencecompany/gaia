"use client";

import type React from "react";

import { InViewMount } from "../shared/InViewMount";
import { SoftBlurInBlock, TextSoftBlurIn } from "../shared/TextSoftBlurIn";

interface ShowcaseSectionLayoutProps {
  header?: string;
  subheader?: string;
  DemoComponent: React.ReactNode;
  SidebarContent: React.ReactNode;
  sidebarClassName?: string;
  containerClassName?: string;
}

export default function ShowcaseSectionLayout({
  header,
  subheader,
  DemoComponent,
  SidebarContent,
  sidebarClassName = "flex w-full flex-col justify-end gap-7 lg:w-[25%] pb-13",
  containerClassName = "relative mx-auto mb-8 sm:mb-16 lg:mb-20 flex w-full flex-col justify-center px-6 sm:px-6",
}: ShowcaseSectionLayoutProps) {
  return (
    <div className={containerClassName}>
      {/* Header — optional */}
      {header && (
        <SoftBlurInBlock className="mb-5 text-xl font-light text-primary sm:text-2xl text-center lg:text-left">
          {header}
        </SoftBlurInBlock>
      )}
      {subheader && (
        <TextSoftBlurIn
          text={subheader}
          className="mb-8 font-serif text-4xl font-normal sm:text-5xl text-center lg:text-left"
        />
      )}

      {/* 70/30 split */}
      <div className="flex flex-col gap-6 lg:flex-row lg:gap-8">
        {/* Left: 70% — Animation showcase. Lazy-mounted so its heavy animation
            stays off the initial-load path, while the header/subheader/sidebar
            copy stays server-rendered for SEO. */}
        <div className="w-full lg:w-[70%]">
          <InViewMount minHeight="70vh">{DemoComponent}</InViewMount>
        </div>

        {/* Right: 30% — Sidebar content */}
        <div className={sidebarClassName}>{SidebarContent}</div>
      </div>
    </div>
  );
}
