import { BreadcrumbItem, Breadcrumbs } from "@heroui/react";
import type { ReactNode } from "react";

import { RaisedButton } from "@/components";

import PublishWorkflowCTA from "./PublishWorkflowCTA";
import ShareButton from "./ShareButton";
import YouMightAlsoLike from "./YouMightAlsoLike";

interface UseCaseDetailLayoutProps {
  breadcrumbs: Array<{ label: string; href?: string }>;
  title: string;
  description?: string;
  id: string;
  isCreating: boolean;
  onCreateWorkflow: () => void;
  metaInfo: ReactNode;
  detailedContent?: ReactNode;
  steps?: ReactNode;
  similarContent?: ReactNode;
  categories?: string[];
}

export default function UseCaseDetailLayout({
  breadcrumbs,
  title,
  description,
  id,
  isCreating,
  onCreateWorkflow,
  metaInfo,
  detailedContent,
  steps,
  similarContent,
  categories,
}: UseCaseDetailLayoutProps) {
  return (
    <div className="flex min-h-screen w-screen justify-center overflow-y-auto pt-34 pb-20 relative z-[1]">
      <div className="container mx-auto w-full max-w-5xl space-y-5">
        <div className="mb-3 text-sm text-zinc-500">
          <Breadcrumbs>
            {breadcrumbs.map((crumb) => (
              <BreadcrumbItem key={crumb.label} href={crumb.href}>
                {crumb.label}
              </BreadcrumbItem>
            ))}
          </Breadcrumbs>
        </div>

        <div className="flex w-full items-start justify-between gap-2">
          <div className="flex-1 space-y-2">
            <h1 className="text-5xl font-normal text-foreground">{title}</h1>
            {description && (
              <p className="text-lg leading-relaxed text-zinc-500 max-w-5xl mt-6">
                {description}
              </p>
            )}
          </div>

          <div className="flex items-center gap-3">
            <ShareButton id={id} />
            <RaisedButton
              color="#00bbff"
              className="shrink-0 text-black!"
              onClick={onCreateWorkflow}
              disabled={isCreating}
            >
              {isCreating ? "Creating..." : "Add to your GAIA"}
            </RaisedButton>
          </div>
        </div>

        <div className="flex min-h-[40vh] gap-8 flex-col">
          <div className="flex-1 space-y-4">
            <div className="flex flex-wrap items-start gap-2">{metaInfo}</div>

            {detailedContent}
          </div>

          {steps}
        </div>

        {similarContent}

        <YouMightAlsoLike currentSlug={id} categories={categories} />

        <PublishWorkflowCTA />
      </div>
    </div>
  );
}
