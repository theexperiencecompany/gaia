"use client";

import { ArrowLeft01Icon } from "@icons";
import { notFound, useParams } from "next/navigation";
import { useState } from "react";

import RightSidebarPanel from "@/components/layout/sidebar/RightSidebarPanel";
import RightSidebarSlot, {
  RightSidebarSlotProvider,
} from "@/components/layout/sidebar/RightSidebarSlot";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { LinkButton } from "@/components/shared/LinkButton";
import { TaskIconTile } from "../../tasks/TaskIconTile";
import TaskPanel from "../../tasks/TaskPanel";
import TaskSection from "../../tasks/TaskSection";
import type { Task } from "../../tasks/taskModel";
import { TemplateFacts } from "../TemplateFacts";
import { EXPLORE_PATH, TemplateRow } from "../TemplateRow";
import {
  CONNECTED_APPS,
  TEMPLATES,
  taskFromTemplate,
  toTemplate,
} from "../templateModel";

/** How many neighbours "More in" lists under a template. */
const RELATED_ROWS = 4;

export default function TemplatePage() {
  const { slug } = useParams<{ slug: string }>();
  const [task, setTask] = useState<Task | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const data = TEMPLATES.find((item) => item.slug === slug);
  if (!data) notFound();
  const template = toTemplate(data);
  const category = data.categories[0];
  const related = TEMPLATES.filter(
    (item) =>
      item.id !== data.id && category && item.categories.includes(category),
  )
    .slice(0, RELATED_ROWS)
    .map(toTemplate);

  const use = () => {
    setTask((made) => made ?? taskFromTemplate(template, CONNECTED_APPS));
    setIsOpen(true);
  };

  return (
    <RightSidebarSlotProvider>
      <div className="dark relative flex h-dvh w-full bg-primary-bg text-zinc-100 selection:bg-[#00364b] selection:text-accent">
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[46rem] px-5 pb-32 pt-10">
            <LinkButton
              href={EXPLORE_PATH}
              size="sm"
              variant="quiet"
              tone="muted"
              hoverTone="bright"
              inset="tight"
              className="h-9 min-w-0 gap-1.5 text-sm"
            >
              <ArrowLeft01Icon className="size-4" />
              Explore
            </LinkButton>

            <header className="mt-8 px-2">
              <TaskIconTile icon={template.icon} size={40} />
              <h1 className="mt-4 text-[28px] font-semibold leading-tight tracking-[-0.02em] text-white">
                {data.title}
              </h1>
              <p className="mt-1.5 text-[15px] leading-6 text-zinc-400">
                {data.summary}
              </p>
              <GaiaButton
                size="sm"
                variant="tertiary"
                tone="strong"
                onPress={use}
                className="mt-6 h-9 text-sm"
              >
                Use this
              </GaiaButton>
            </header>

            <div className="mt-8 px-2">
              <TemplateFacts
                template={template}
                categoryHref={(name) =>
                  `${EXPLORE_PATH}?category=${encodeURIComponent(name)}`
                }
              />
            </div>

            <section aria-labelledby="brief" className="mt-8 px-2">
              <h2 id="brief" className="text-[13px] font-medium text-zinc-500">
                What GAIA does
              </h2>
              <p className="mt-2 whitespace-pre-line text-[15px] leading-7 text-zinc-200">
                {data.body}
              </p>
            </section>

            {related.length > 0 && (
              <div className="mt-14">
                <TaskSection id="related" title={`More in ${category}`}>
                  <ul>
                    {related.map((item) => (
                      <TemplateRow key={item.data.id} template={item} />
                    ))}
                  </ul>
                </TaskSection>
              </div>
            )}
          </div>
        </main>
        <RightSidebarSlot />
      </div>

      {task && isOpen && (
        <RightSidebarPanel mode="sidebar" onClose={() => setIsOpen(false)}>
          {/* A task fresh from a template has no ask, offer, parent or subtasks yet. */}
          <TaskPanel
            task={task}
            childTasks={[]}
            onChange={setTask}
            onAnswer={() => undefined}
            onOpen={() => undefined}
            onAcceptOffer={() => undefined}
            onDelete={() => {
              setTask(null);
              setIsOpen(false);
            }}
          />
        </RightSidebarPanel>
      )}
    </RightSidebarSlotProvider>
  );
}
