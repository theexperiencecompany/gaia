import type { SkillTarget } from "./api/types";

/** Case-insensitive match of a query against a skill's name + description. */
export function skillMatchesQuery(
  name: string,
  description: string,
  query: string,
): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    name.toLowerCase().includes(q) || description.toLowerCase().includes(q)
  );
}

/** Build a value→target lookup from the targets list. */
export function buildTargetMap(
  targets: SkillTarget[],
): Map<string, SkillTarget> {
  return new Map(targets.map((t) => [t.value, t]));
}
