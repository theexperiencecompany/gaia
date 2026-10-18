interface TitledWorkflow {
  readonly title: string;
}

function titleKey(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** The official template a community workflow republishes under the same title, if any. */
export function findCopiedTemplate<T extends TitledWorkflow>(
  workflow: TitledWorkflow,
  templates: readonly T[],
): T | undefined {
  const key = titleKey(workflow.title);
  return templates.find((template) => titleKey(template.title) === key);
}
