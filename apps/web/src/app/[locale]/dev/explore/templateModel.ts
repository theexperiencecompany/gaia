/**
 * A template as GET /templates is planned to send it (one task_templates row),
 * and the view the Explore pages render from it. The fixture is production's
 * explore and community workflows, converted by field.
 */

import type { WorkflowCreator } from "@shared/api/generated";

import { isRepeating, type Task, type TaskWhen } from "../tasks/taskModel";
import { NO_WHEN, onEvent, onSchedule } from "../tasks/whenModel";
import FIXTURE from "./templates.fixture.json";

/** The task's `when`, minus `date`: a template never carries a one-off date. */
export type TemplateWhenData =
  | { kind: "none" }
  | { kind: "repeat"; cron: string; timezone: string }
  | { kind: "event"; trigger_name: string };

/** One row of task_templates. `summary` is the field the planned model lacks today. */
export interface TemplateData {
  id: string;
  slug: string;
  title: string;
  /** One line, what you get. From workflow `description`. */
  summary: string;
  /** The brief the new task starts with. From workflow `prompt`. */
  body: string;
  icon: string | null;
  icon_color: string | null;
  when: TemplateWhenData;
  integration_ids: string[];
  /** The publisher, as workflows carry it today. */
  creator: WorkflowCreator;
  categories: string[];
  /** Curated by GAIA; sorts first. From the "featured" pseudo-category. */
  featured: boolean;
  /** A system task (Meeting Briefing): "Use this" turns on the one the user already has. */
  system_key: string | null;
  published_at: string | null;
}

const GAIA_CREATOR_ID = "system";

export interface Template {
  data: TemplateData;
  when: TaskWhen;
  icon?: { name: string; color: string };
  isByGaia: boolean;
}

function whenOf(when: TemplateWhenData): TaskWhen {
  if (when.kind === "repeat") return onSchedule(when.cron, when.timezone);
  if (when.kind === "event") return onEvent(when.trigger_name);
  return { kind: "anytime", label: "When you ask" };
}

export function toTemplate(data: TemplateData): Template {
  return {
    data,
    when: whenOf(data.when),
    icon:
      data.icon && data.icon_color
        ? { name: data.icon, color: data.icon_color }
        : undefined,
    isByGaia: data.creator.id === GAIA_CREATOR_ID,
  };
}

export const TEMPLATES: TemplateData[] = FIXTURE as TemplateData[];

/** The fixture repeated up to `count` rows, to see the page at catalogue scale. */
export function atScale(count: number): TemplateData[] {
  return Array.from({ length: count }, (_, index) => {
    const source = TEMPLATES[index % TEMPLATES.length];
    const copy = Math.floor(index / TEMPLATES.length);
    return copy === 0
      ? source
      : {
          ...source,
          id: `${source.id}_${copy}`,
          slug: `${source.slug}-${copy}`,
        };
  });
}

/** The demo user's connected apps, so "Use this" can show asking for the rest. */
export const CONNECTED_APPS = ["googlecalendar"];

/**
 * What POST /templates/{ref}/use returns: a GAIA task with the template's
 * name, brief, icon, when and apps. One whose app isn't connected starts paused
 * (blocked_on_integrations), and its Apps row offers to connect it.
 */
export function taskFromTemplate(
  template: Template,
  connected: string[],
): Task {
  const { data } = template;
  const missing = data.integration_ids.filter(
    (app) => !connected.includes(app),
  );
  const repeats = isRepeating(template.when);
  return {
    id: crypto.randomUUID(),
    title: data.title,
    instructions: data.body,
    assignee: "gaia",
    state: missing.length > 0 ? "paused" : repeats ? "standing" : "open",
    when: repeats ? template.when : NO_WHEN,
    icon: template.icon,
    integrations: data.integration_ids,
    disconnected: missing,
    pauseReason: missing.length > 0 ? "integration_missing" : undefined,
    priority: "none",
    checklist: [],
    runs: [],
    notify: true,
  };
}

/** Who made it, as the byline reads: GAIA's own are signed "GAIA", not "GAIA Team". */
export function creatorLabel(template: Template): string {
  return template.isByGaia ? "GAIA" : template.data.creator.name;
}
