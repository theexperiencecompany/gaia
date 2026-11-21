"use client";

import { PlusSignIcon } from "@icons";
import { createContext, type ReactNode, useContext, useState } from "react";
import RightSidebarPanel from "@/components/layout/sidebar/RightSidebarPanel";
import RightSidebarSlot, {
  RightSidebarSlotProvider,
} from "@/components/layout/sidebar/RightSidebarSlot";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { LinkButton } from "@/components/shared/LinkButton";
import { toast } from "@/lib/toast";
import { EXPLORE_PATH } from "../explore/TemplateRow";
import { DEMO_TASKS } from "./demoTasks";
import { NewGaiaTask } from "./NewGaiaTask";
import { blankTask, NewTodoRow } from "./NewTask";
import NewTaskButton from "./NewTaskButton";
import type { AskAnswer } from "./TaskAsk";
import TaskPanel from "./TaskPanel";
import TaskRow from "./TaskRow";
import TaskSection from "./TaskSection";
import { type Assignee, isRepeating, needOf, type Task } from "./taskModel";

/** Soonest first: overdue, today, upcoming, then tasks with no date. */
function byDate(a: Task, b: Task): number {
  return (
    (a.when.order ?? Number.POSITIVE_INFINITY) -
    (b.when.order ?? Number.POSITIVE_INFINITY)
  );
}

/** The run an answer wakes, as its record reads. */
const ANSWERED: {
  [K in AskAnswer["kind"]]: (answer: AskAnswer) => string;
} = {
  approve: () => "Sent it after you approved",
  deny: () => "Left it unsent, as you asked",
  reply: (answer) =>
    answer.kind === "reply" ? `Picked up your reply: ${answer.text}` : "",
};

/** The id of the task open in the sidebar, so its row can show as selected. */
const SelectedTask = createContext<string | undefined>(undefined);

/** A task's subtasks: tasks filed under it, then its checklist items as the same kind of row. */
function subtasksOf(task: Task, all: Task[]): Task[] {
  const filed = all.filter((other) => other.parentId === task.id);
  const ticks: Task[] = task.checklist.map((item) => ({
    id: item.id,
    parentId: task.id,
    title: item.title,
    assignee: task.assignee,
    state: item.completed ? "done" : "open",
    when: { kind: "anytime" },
    priority: "none",
    integrations: [],
    checklist: [],
    runs: [],
    notify: false,
  }));
  return [...filed, ...ticks];
}

function Rows({
  tasks,
  all,
  onToggleDone,
  onOpen,
}: {
  tasks: Task[];
  all: Task[];
  onToggleDone: (task: Task) => void;
  onOpen: (task: Task) => void;
}) {
  const selectedId = useContext(SelectedTask);
  return (
    <ul>
      {tasks.map((task) => {
        const subtasks = task.parentId ? [] : subtasksOf(task, all);
        const parent = all.find((other) => other.id === task.parentId);
        return (
          <TaskRow
            key={task.id}
            task={task}
            onToggleDone={onToggleDone}
            onOpen={onOpen}
            isSelected={task.id === selectedId}
            parentTitle={parent?.title}
            subtasks={
              subtasks.length > 0
                ? {
                    done: subtasks.filter((item) => item.state === "done")
                      .length,
                    total: subtasks.length,
                  }
                : undefined
            }
          />
        );
      })}
    </ul>
  );
}

/**
 * One owner's tasks. Open ones first, today's finished ones crossed out below,
 * older finished ones behind the count in the heading. GAIA's repeating tasks,
 * which never finish, sit under their own label.
 */
function OwnerSection({
  id,
  title,
  tasks,
  all,
  splitRepeating = false,
  onToggleDone,
  onOpen,
  onNew,
  draftRow,
}: {
  id: string;
  title: string;
  tasks: Task[];
  all: Task[];
  splitRepeating?: boolean;
  onToggleDone: (task: Task) => void;
  onOpen: (task: Task) => void;
  onNew: () => void;
  /** A to-do being typed, shown above this section's rows. */
  draftRow?: ReactNode;
}) {
  const [showEarlier, setShowEarlier] = useState(false);
  const open = tasks.filter((task) => task.state !== "done").sort(byDate);
  const done = tasks.filter((task) => task.state === "done");
  const doneToday = done.filter((task) => task.doneToday);
  const earlier = done.filter((task) => !task.doneToday);
  const repeating = splitRepeating
    ? open.filter((task) => isRepeating(task.when))
    : [];
  const oneOff = open.filter((task) => !repeating.includes(task));
  // A new task has no date, so it is typed where undated tasks begin and lands exactly there.
  const dated = oneOff.filter((task) => task.when.order !== undefined);
  const undated = oneOff.filter((task) => task.when.order === undefined);

  return (
    <TaskSection
      id={id}
      title={title}
      count={open.length}
      action={
        <div className="flex items-center gap-1">
          {earlier.length > 0 && (
            <GaiaButton
              size="sm"
              variant="quiet"
              tone="faint"
              hoverTone="bright"
              inset="tight"
              aria-expanded={showEarlier}
              onPress={() => setShowEarlier((shown) => !shown)}
              className="h-7 min-w-0 text-[13px] leading-[1.5]"
            >
              {showEarlier ? "Hide completed" : `${earlier.length} completed`}
            </GaiaButton>
          )}
          <GaiaButton
            isIconOnly
            size="sm"
            variant="quiet"
            tone="faint"
            hoverTone="bright"
            aria-label={`New task: ${title}`}
            onPress={onNew}
            className="size-7 min-w-7"
          >
            <PlusSignIcon className="size-4" />
          </GaiaButton>
        </div>
      }
    >
      <Rows
        tasks={dated}
        all={all}
        onToggleDone={onToggleDone}
        onOpen={onOpen}
      />
      {draftRow}
      <Rows
        tasks={[...undated, ...doneToday, ...(showEarlier ? earlier : [])]}
        all={all}
        onToggleDone={onToggleDone}
        onOpen={onOpen}
      />
      {repeating.length > 0 && (
        <>
          <h3 className="px-2 pb-1 pt-6 text-[13px] font-medium text-zinc-500">
            Repeating workflows
          </h3>
          <Rows
            tasks={repeating}
            all={all}
            onToggleDone={onToggleDone}
            onOpen={onOpen}
          />
        </>
      )}
    </TaskSection>
  );
}

export default function TasksDemoPage() {
  const [tasks, setTasks] = useState<Task[]>(DEMO_TASKS);
  const [openTask, setOpenTask] = useState<Task | null>(null);
  const opened = tasks.find((task) => task.id === openTask?.id);
  // An answer wakes the task, so it runs and the run is recorded.
  const answer = (task: Task, given: AskAnswer) =>
    replace({
      ...task,
      ask: undefined,
      state: "running",
      waitingOn: undefined,
      runs: [
        {
          id: crypto.randomUUID(),
          at: "Just now",
          outcome: "success",
          summary: ANSWERED[given.kind](given),
          duration: "1s",
          trigger: "manual",
          trace: [],
        },
        ...task.runs,
      ],
    });
  const [creating, setCreating] = useState<Assignee | null>(null);
  const [published, setPublished] = useState<string[]>([]);
  const publish = (task: Task) => {
    setPublished((ids) => [...ids, task.id]);
    toast.success("Published to Explore", {
      description: "People can find it and make their own copy.",
    });
  };
  const unpublish = (task: Task) => {
    setPublished((ids) => ids.filter((id) => id !== task.id));
    toast.info("Unpublished", {
      description: "Tasks people already made from it keep working.",
    });
  };
  const startNew = (assignee: Assignee) => {
    setOpenTask(null);
    setCreating(assignee);
  };
  const open = (task: Task) => {
    setCreating(null);
    setOpenTask(task);
  };
  const add = (task: Task) => setTasks((current) => [task, ...current]);
  const remove = (gone: Task) => {
    setOpenTask(null);
    setTasks((current) =>
      current.filter(
        (task) => task.id !== gone.id && task.parentId !== gone.id,
      ),
    );
  };
  const replace = (next: Task) =>
    setTasks((current) =>
      current.map((task) => (task.id === next.id ? next : task)),
    );

  /** Ticks a task, or the checklist item a step row stands for. */
  const toggleDone = (target: Task) =>
    setTasks((current) =>
      current.map((task) => {
        if (task.id === target.id) {
          return task.state === "done"
            ? { ...task, state: "open", doneToday: false }
            : { ...task, state: "done", doneToday: true };
        }
        if (task.id !== target.parentId) return task;
        return {
          ...task,
          checklist: task.checklist.map((item) =>
            item.id === target.id
              ? { ...item, completed: !item.completed }
              : item,
          ),
        };
      }),
    );

  // GAIA's offer on a to-do becomes a task GAIA owns, filed under the to-do.
  const acceptOffer = (todo: Task, title: string) =>
    setTasks((current) => [
      ...current.map((task) =>
        task.id === todo.id ? { ...task, offer: undefined } : task,
      ),
      {
        ...blankTask("gaia"),
        title,
        parentId: todo.id,
        status: "Getting started",
      },
    ]);

  const needsYou = tasks.filter((task) => needOf(task));
  const topLevel = tasks.filter((task) => !task.parentId);
  const mine = topLevel.filter((task) => task.assignee === "you");
  const gaias = topLevel.filter(
    (task) => task.assignee === "gaia" && !needsYou.includes(task),
  );

  return (
    <RightSidebarSlotProvider>
      <SelectedTask.Provider value={opened?.id}>
        <div className="dark relative flex h-dvh w-full bg-primary-bg text-zinc-100 selection:bg-[#00364b] selection:text-accent">
          <main className="min-w-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-[46rem] space-y-11 px-5 pb-32 pt-16">
              <div className="flex items-center justify-between px-2">
                <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em] text-white">
                  Tasks
                </h1>
                <div className="flex items-center gap-1">
                  <LinkButton
                    href={EXPLORE_PATH}
                    size="sm"
                    variant="quiet"
                    tone="muted"
                    hoverTone="bright"
                  >
                    Explore
                  </LinkButton>
                  <NewTaskButton onPick={startNew} />
                </div>
              </div>

              {needsYou.length > 0 && (
                <TaskSection
                  id="needs-you"
                  title="Needs you"
                  count={needsYou.length}
                  urgent
                >
                  <Rows
                    tasks={needsYou}
                    all={tasks}
                    onToggleDone={toggleDone}
                    onOpen={open}
                  />
                </TaskSection>
              )}

              <OwnerSection
                id="mine"
                title="On your plate"
                tasks={mine}
                all={tasks}
                onToggleDone={toggleDone}
                onOpen={open}
                onNew={() => startNew("you")}
                draftRow={
                  creating === "you" && (
                    <NewTodoRow
                      onCreate={(title) => {
                        const task = { ...blankTask("you"), title };
                        add(task);
                        open(task);
                      }}
                      onDone={() => setCreating(null)}
                    />
                  )
                }
              />
              <OwnerSection
                id="gaia"
                title="On GAIA's plate"
                tasks={gaias}
                all={tasks}
                splitRepeating
                onToggleDone={toggleDone}
                onOpen={open}
                onNew={() => startNew("gaia")}
              />
            </div>
          </main>
          <RightSidebarSlot />
        </div>

        {(opened || creating === "gaia") && (
          <RightSidebarPanel
            mode="sidebar"
            onClose={() => {
              setOpenTask(null);
              setCreating(null);
            }}
          >
            {opened ? (
              <TaskPanel
                key={opened.id}
                task={opened}
                parent={tasks.find((task) => task.id === opened.parentId)}
                childTasks={tasks.filter((task) => task.parentId === opened.id)}
                onChange={replace}
                onAnswer={answer}
                onDelete={remove}
                onOpen={open}
                onAcceptOffer={acceptOffer}
                isPublished={published.includes(opened.id)}
                onPublish={() => publish(opened)}
                onUnpublish={() => unpublish(opened)}
              />
            ) : (
              <NewGaiaTask
                onCreate={(task) => {
                  add(task);
                  open(task);
                }}
              />
            )}
          </RightSidebarPanel>
        )}
      </SelectedTask.Provider>
    </RightSidebarSlotProvider>
  );
}
