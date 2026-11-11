import type { CommunityWorkflow } from "@/features/workflows/api/workflowApi";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";

interface YouMightAlsoLikeProps {
  /** Server-picked by relatedUseCases, so the links are in the SSR HTML. */
  readonly workflows: readonly CommunityWorkflow[];
}

export default function YouMightAlsoLike({ workflows }: YouMightAlsoLikeProps) {
  if (workflows.length === 0) return null;

  return (
    <div className="mx-auto max-w-5xl">
      <div className="my-20 border border-t border-zinc-900" />
      <div className="mx-auto space-y-6">
        <h2 className="mx-auto text-center font-serif text-6xl font-normal text-foreground">
          You might also like
        </h2>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {workflows.map((workflow) => (
            <UnifiedWorkflowCard
              key={workflow.id}
              communityWorkflow={workflow}
              variant="community"
              showCreator={true}
              href={workflow.slug ? `/use-cases/${workflow.slug}` : undefined}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
