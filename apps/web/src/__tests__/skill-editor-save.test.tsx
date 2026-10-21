// @vitest-environment jsdom
/**
 * What the skill editor sends when it saves: a new skill in full, an edit without its fixed name.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createSkill = vi.fn();
const updateSkill = vi.fn();

vi.mock("@/features/skills/api/skillsApi", () => ({
  skillsApi: {
    createSkill: (body: unknown) => createSkill(body),
    updateSkill: (id: string, body: unknown) => updateSkill(id, body),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock("@/features/chat/components/interface/MarkdownRenderer", () => ({
  default: () => null,
}));

vi.mock("@/features/skills/components/SkillImportForm", () => ({
  SkillImportForm: () => null,
}));

vi.mock("@/features/skills/components/SkillTargetSelect", () => ({
  SkillTargetSelect: () => null,
}));

import type { Skill } from "@/features/skills/api/types";
import { SkillEditorModal } from "@/features/skills/components/SkillEditorModal";
import { EXECUTOR_TARGET } from "@/features/skills/constants";

const existing = {
  id: "skill-1",
  name: "triage-inbox",
  description: "Sort new mail",
  body_content: "1. Fetch unread mail",
  target: EXECUTOR_TARGET,
} as Skill;

function renderEditor(skill: Skill | null) {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  render(
    <SkillEditorModal
      isOpen
      onClose={onClose}
      onSaved={onSaved}
      targets={[]}
      skill={skill}
    />,
  );
  return { onSaved, onClose };
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("SkillEditorModal saving", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createSkill.mockResolvedValue({});
    updateSkill.mockResolvedValue({});
  });

  it("creates a new skill from every field, with the description trimmed", async () => {
    const { onSaved, onClose } = renderEditor(null);

    type("Name", "weekly-report");
    type("Description", "  Summarise the week  ");
    type("Instructions", "# Weekly report");
    fireEvent.click(screen.getByRole("button", { name: "Create skill" }));

    await waitFor(() =>
      expect(createSkill).toHaveBeenCalledWith({
        name: "weekly-report",
        description: "Summarise the week",
        instructions: "# Weekly report",
        target: EXECUTOR_TARGET,
      }),
    );
    expect(updateSkill).not.toHaveBeenCalled();
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("updates an existing skill by id and never sends its name", async () => {
    renderEditor(existing);

    type("Description", "Sort and label new mail ");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(updateSkill).toHaveBeenCalledWith("skill-1", {
        description: "Sort and label new mail",
        instructions: "1. Fetch unread mail",
        target: EXECUTOR_TARGET,
      }),
    );
    expect(createSkill).not.toHaveBeenCalled();
  });

  it("will not create a skill whose name breaks the naming rule", () => {
    renderEditor(null);

    type("Name", "Weekly Report");
    type("Description", "Summarise the week");
    type("Instructions", "# Weekly report");

    expect(screen.getByRole("button", { name: "Create skill" })).toHaveProperty(
      "disabled",
      true,
    );
  });
});
