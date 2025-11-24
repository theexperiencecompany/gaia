import { Chip } from "@heroui/chip";
import type { ReactNode } from "react";

export function SectionHeading({
  heading,
  subheading,
  icon,
  className,
  chipTitle,
  chipTitle2,
  smallHeading = false,
  headingClassName,
  subheadingClassName = "max-w-screen-sm",
}: {
  heading: string;
  subheading?: string | ReactNode;
  icon?: ReactNode;
  chipTitle?: string;
  chipTitle2?: string;
  smallHeading?: boolean;
  className?: string;
  headingClassName?: string;
  subheadingClassName?: string;
}) {
  return (
    <div className={`relative z-[1] p-7 sm:p-0 ${className}`}>
      {(chipTitle2 || chipTitle) && (
        <div className="mb-2 flex items-center gap-2">
          {chipTitle && (
            <Chip variant="flat" color="primary">
              {chipTitle}
            </Chip>
          )}

          {chipTitle2 && (
            <Chip variant="flat" color="warning">
              {chipTitle2}
            </Chip>
          )}
        </div>
      )}
      <div
        className={`${
          smallHeading ? "sm:text-3xl" : "sm:text-4xl"
        } ${headingClassName} mb-2 flex items-center gap-4 text-3xl font-semibold`}
      >
        {icon}
        <span>{heading}</span>
      </div>
      {!!subheading && (
        <div
          className={`${subheadingClassName} text-foreground-500 ${
            smallHeading ? "text-md" : "text-lg"
          }`}
        >
          {subheading}
        </div>
      )}
    </div>
  );
}
