import { getToolDisplayName } from "@shared/icons";
import { fitDescription, fitTitle } from "@/lib/seo";
import type { TriggerConfig, UseCase } from "@/types/features/workflowTypes";

/** The step category for GAIA's own reasoning step, which the "GAIA workflow" wording already names. */
const GAIA_STEP_CATEGORY = "gaia";

/** Step categories that are GAIA itself rather than an app a searcher would name. */
const BUILT_IN_STEP_CATEGORIES: ReadonlySet<string> = new Set([
  GAIA_STEP_CATEGORY,
  "todos",
  "tracked_todos",
  "reminders",
  "documents",
  "memory",
  "search",
]);

const TRIGGER_SENTENCES: Record<TriggerConfig["type"], string> = {
  manual: "Run it whenever you need it.",
  schedule: "Runs on a schedule.",
  integration: "Runs on its own when a connected app sends a new event.",
  scheduled_todo: "Runs when a scheduled todo comes due.",
  todo_trigger: "Runs when your todos change.",
};

/** Searchers prefix "ai" ("ai rent reminder", "ai assignment tracker"); titles that already say AI keep theirs. */
function withAiLead(title: string): string {
  return /\bAI\b/.test(title) ? title : `AI ${title}`;
}

function uniqueDisplayNames(categories: readonly string[]): string[] {
  return [...new Set(categories.map(getToolDisplayName))];
}

/** Title for /use-cases/[slug]: the task as searched, then the apps it runs on. */
export function generateUseCaseTitle(
  useCase: Pick<UseCase, "title" | "integrations">,
): string {
  const lead = withAiLead(useCase.title);
  const [first, second] = uniqueDisplayNames(
    useCase.integrations.filter(
      (category) => !BUILT_IN_STEP_CATEGORIES.has(category),
    ),
  );
  const workflowSuffixes = /\bworkflow\b/i.test(useCase.title)
    ? []
    : [`${lead}: Automated Workflow`, `${lead} Workflow`];
  return fitTitle([
    ...(first && second ? [`${lead} with ${first} and ${second}`] : []),
    ...(first ? [`${lead} with ${first}`] : []),
    ...workflowSuffixes,
    lead,
  ]);
}

/** Description for /use-cases/[slug]: what it does, how many steps across which apps, and when it runs. */
export function generateUseCaseDescription(
  useCase: Pick<
    UseCase,
    | "description"
    | "detailed_description"
    | "integrations"
    | "steps"
    | "trigger_config"
  >,
): string {
  const stepCount = useCase.steps?.length ?? useCase.integrations.length;
  const apps = uniqueDisplayNames(
    useCase.integrations.filter((category) => category !== GAIA_STEP_CATEGORY),
  );
  const appList =
    apps.length > 1
      ? `${apps.slice(0, -1).join(", ")} and ${apps.at(-1)}`
      : apps[0];
  const workflowSentence = appList
    ? `A ${stepCount}-step GAIA workflow using ${appList}.`
    : `A ${stepCount}-step GAIA workflow.`;
  const triggerType = useCase.trigger_config?.type;
  return fitDescription([
    useCase.detailed_description || useCase.description,
    stepCount > 0 ? workflowSentence : "",
    triggerType ? TRIGGER_SENTENCES[triggerType] : "",
    "Add it to your GAIA from this page.",
  ]);
}
