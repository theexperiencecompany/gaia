"use client";

import { CheckmarkCircleIcon } from "@icons";
import type { PublicIntegrationResponse } from "@/features/integrations/types";

interface IntegrationUseCasesProps {
  readonly integration: PublicIntegrationResponse;
}

export function IntegrationUseCases({ integration }: IntegrationUseCasesProps) {
  const useCases = integration.content?.useCases ?? [];
  if (useCases.length === 0) return null;

  return (
    <section className="rounded-3xl bg-zinc-900/50 backdrop-blur-md p-8 space-y-6">
      <div>
        <h2 className="text-2xl font-medium text-foreground mb-2">
          What you can do with GAIA
        </h2>
        <p className="text-zinc-400 text-sm leading-relaxed">
          GAIA connects to it via MCP (Model Context Protocol) and exposes every
          action as a natural-language command. Tell GAIA what you want and it
          handles the rest, automatically.
        </p>
      </div>
      <ul className="space-y-3">
        {useCases.map((useCase) => (
          <li
            key={useCase}
            className="flex items-start gap-3 text-zinc-300 text-sm"
          >
            <CheckmarkCircleIcon
              className="mt-0.5 flex-shrink-0 h-5 w-5 text-[#00bbff]"
              aria-hidden="true"
            />
            {useCase}
          </li>
        ))}
      </ul>
    </section>
  );
}
