import { Chip } from "@heroui/chip";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { SoftBlurInBlock, TextSoftBlurIn } from "./TextSoftBlurIn";

export default function LargeHeader({
  chipText,
  headingText,
  subHeadingText,
  chipText2,
  centered = false,
}: {
  chipText?: ReactNode;
  chipText2?: ReactNode;
  headingText: ReactNode;
  subHeadingText?: ReactNode;
  centered?: boolean;
}) {
  const headingClass = cn(
    "relative z-2 my-2 text-4xl font-medium sm:text-5xl md:text-7xl font-serif!",
    centered ? "text-center" : "text-left",
  );

  return (
    <div
      className={`flex max-w-(--breakpoint-xl) flex-col ${centered ? "items-center text-center" : "items-start text-left"}`}
    >
      <div
        className={`flex w-full gap-1 ${centered ? "items-center justify-center" : "items-start justify-start"}`}
      >
        {chipText && (
          <div className="text-primary uppercase mb-2">{chipText}</div>
        )}

        {chipText2 && (
          <Chip variant="flat" color="danger">
            {chipText2}
          </Chip>
        )}
      </div>

      {typeof headingText === "string" ? (
        <TextSoftBlurIn text={headingText} as="h2" className={headingClass} />
      ) : (
        <SoftBlurInBlock as="h2" className={headingClass}>
          {headingText}
        </SoftBlurInBlock>
      )}

      {!!subHeadingText && (
        <SoftBlurInBlock
          className={cn(
            "max-w-(--breakpoint-md) text-base sm:text-xl text-zinc-400 font-light",
            centered && "text-center",
          )}
        >
          {subHeadingText}
        </SoftBlurInBlock>
      )}
    </div>
  );
}
