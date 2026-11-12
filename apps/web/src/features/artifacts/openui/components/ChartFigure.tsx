import type { ReactNode } from "react";
import { GroundedText } from "../GroundedText";

interface FigureProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export function Figure({ title, subtitle, children }: FigureProps) {
  return (
    <figure className="flex min-w-0 flex-col gap-2">
      <figcaption>
        <span className="font-semibold text-foreground">
          <GroundedText text={title} />
        </span>
        {subtitle ? (
          <span className="block text-sm text-default-500">
            <GroundedText text={subtitle} />
          </span>
        ) : null}
      </figcaption>
      {children}
    </figure>
  );
}
