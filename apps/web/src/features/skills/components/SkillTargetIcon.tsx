import { AiMagicIcon, BookOpen01Icon, Note01Icon } from "@icons";
import type { ComponentType, SVGProps } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { EXECUTOR_TARGET } from "../constants";

interface SkillTargetIconProps {
  /** Target value (executor or a subagent agent_name). */
  value: string;
  /** Icon key (integration id, or "executor"). */
  icon: string;
  size?: number;
}

/** Built-in (non-integration) subagents have no logo — give them a proper glyph. */
const BUILTIN_ICONS: Record<string, ComponentType<SVGProps<SVGSVGElement>>> = {
  docgen: Note01Icon,
  gaia_knowledge_guide: BookOpen01Icon,
};

/**
 * Renders the logo for a skill target: a magic-wand glyph for the general
 * assistant, a proper glyph for built-in subagents, otherwise the owning
 * integration's logo (resolved by id).
 */
export function SkillTargetIcon({
  value,
  icon,
  size = 16,
}: SkillTargetIconProps) {
  if (value === EXECUTOR_TARGET || icon === EXECUTOR_TARGET) {
    return (
      <AiMagicIcon
        className="text-primary"
        style={{ width: size, height: size }}
      />
    );
  }

  const Builtin = BUILTIN_ICONS[icon] ?? BUILTIN_ICONS[value];
  if (Builtin) {
    return (
      <Builtin
        className="text-zinc-300"
        style={{ width: size, height: size }}
      />
    );
  }

  return (
    <>
      {getToolCategoryIcon(icon, {
        size,
        width: size,
        height: size,
        showBackground: false,
      })}
    </>
  );
}
