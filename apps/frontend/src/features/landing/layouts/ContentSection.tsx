"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface Layout1Props {
  children: ReactNode;
  heading: string;
  subheading: string;
  icon?: ReactNode;
  extraHeading?: ReactNode;
  className?: string;
  logoInline?: boolean;
}

export default function ContentSection({
  children,
  heading,
  subheading,
  icon,
  extraHeading,
  className,
  logoInline = false,
}: Layout1Props) {
  return (
    <div
      className={cn(
        "flex w-full flex-col items-center justify-start rounded-3xl bg-zinc-900 p-6 transition-all hover:outline-primary sm:h-full sm:min-h-fit sm:gap-7",
        className,
      )}
    >
      <div className="flex w-full flex-col items-start justify-start gap-5">
        {logoInline ? (
          <div className="mb-1 flex flex-col items-start gap-1">
            <div className="flex items-center gap-3">
              {icon}
              <h2 className="text-2xl font-semibold text-white">{heading}</h2>
            </div>
            <p className="text-md mb-2 text-gray-400">{subheading}</p>
            {extraHeading}
          </div>
        ) : (
          <div className="flex flex-col items-start gap-3">
            {icon}
            <div>
              <h2 className="text-3xl font-semibold text-white">{heading}</h2>
              <p className="text-md text-gray-400">{subheading}</p>
            </div>
            {extraHeading}
          </div>
        )}
      </div>
      <div className="w-full space-y-5 rounded-3xl p-3 sm:p-0">{children}</div>
    </div>
  );
}
