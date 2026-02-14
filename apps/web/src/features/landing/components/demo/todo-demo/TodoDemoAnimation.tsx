"use client";

import { Button } from "@heroui/button";
import { ArrowRight02Icon, RedoIcon } from "@icons";
import { AnimatePresence, m, useInView, useReducedMotion } from "motion/react";
import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import DemoTodoComplete from "./DemoTodoComplete";
import DemoTodoList from "./DemoTodoList";
import DemoTodoModal from "./DemoTodoModal";
import DemoTodoRun from "./DemoTodoRun";
import DemoTodoWorkflow from "./DemoTodoWorkflow";
import { TODO_TIMINGS, type TodoDemoPhase, tdEase } from "./todoDemoConstants";

const PHASE_ORDER: TodoDemoPhase[] = [
  "idle",
  "modal_appear",
  "modal_submit",
  "todos_appear",
  "todo_highlighted",
  "workflow_appear",
  "workflow_ready",
  "run_click",
  "executing",
  "todo_complete",
  "done",
];

export default function TodoDemoAnimation() {
  const [phase, setPhase] = useState<TodoDemoPhase>("idle");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const hasStarted = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const prefersReduced = useReducedMotion();
  const isInView = useInView(containerRef, { once: true, amount: 0.3 });

  const clearAll = () => {
    for (const t of timers.current) clearTimeout(t);
    timers.current = [];
  };

  const add = (fn: () => void, delay: number) => {
    timers.current.push(setTimeout(fn, delay));
  };

  const runAnimation = useCallback(() => {
    const T = TODO_TIMINGS;
    clearAll();
    setPhase("idle");
    add(() => setPhase("modal_appear"), T.modalAppear);
    add(() => setPhase("modal_submit"), T.modalSubmit);
    add(() => setPhase("todos_appear"), T.todosAppear);
    add(() => setPhase("todo_highlighted"), T.todoHighlighted);
    add(() => setPhase("workflow_appear"), T.workflowAppear);
    add(() => setPhase("workflow_ready"), T.workflowReady);
    add(() => setPhase("run_click"), T.runClick);
    add(() => setPhase("executing"), T.executing);
    add(() => setPhase("todo_complete"), T.todoComplete);
    add(() => setPhase("done"), T.done);
    add(() => runAnimation(), T.loop);
  }, []);

  const goToPhase = useCallback((p: TodoDemoPhase) => {
    clearAll();
    setPhase(p);
  }, []);

  const prevPhase = useCallback(() => {
    const idx = PHASE_ORDER.indexOf(phase);
    if (idx > 0) goToPhase(PHASE_ORDER[idx - 1]);
  }, [phase, goToPhase]);

  const nextPhase = useCallback(() => {
    const idx = PHASE_ORDER.indexOf(phase);
    if (idx < PHASE_ORDER.length - 1) goToPhase(PHASE_ORDER[idx + 1]);
  }, [phase, goToPhase]);

  useEffect(() => {
    if (isInView && !hasStarted.current) {
      hasStarted.current = true;
      runAnimation();
    }
    return () => clearAll();
  }, [isInView, runAnimation]);

  // Derive which stage group is active
  const showModal = ["modal_appear", "modal_submit"].includes(phase);
  const showList = ["todos_appear", "todo_highlighted"].includes(phase);
  // workflow_appear and workflow_ready only (run_click transitions to run stage)
  const showWorkflowOnly = ["workflow_appear", "workflow_ready"].includes(
    phase,
  );
  const showRun = ["run_click", "executing"].includes(phase);
  const showComplete = ["todo_complete", "done"].includes(phase);

  return (
    <div ref={containerRef} className="flex flex-col items-center gap-4">
      <m.div
        initial={{ opacity: 0, y: 20, scale: 0.97 }}
        whileInView={{ opacity: 1, y: 0, scale: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, ease: tdEase }}
        className="relative flex h-[70vh] w-full items-center justify-center overflow-hidden rounded-2xl"
      >
        {/* Background — same mesh gradient as workflow demo */}
        <m.div
          className="absolute inset-0"
          animate={prefersReduced ? {} : { scale: [1, 1.1, 1] }}
          transition={{ duration: 10, repeat: Infinity, ease: "linear" }}
        >
          <Image
            src="/images/wallpapers/mesh_gradient_1.webp"
            alt="Mesh gradient background"
            width={1920}
            height={1080}
            sizes="100vw"
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              position: "absolute",
              inset: 0,
            }}
            className="object-cover"
            priority
          />
        </m.div>
        <div className="absolute inset-0 bg-black/10 backdrop-blur-sm" />

        {/* Stage content */}
        <div className="relative z-10 flex h-full w-full items-center justify-center px-6">
          <AnimatePresence mode="wait">
            {showModal && (
              <m.div key="stage-modal" className="w-full max-w-lg">
                <DemoTodoModal phase={phase} />
              </m.div>
            )}

            {showList && (
              <m.div key="stage-list" className="w-full max-w-lg">
                <DemoTodoList phase={phase} />
              </m.div>
            )}

            {showWorkflowOnly && (
              <m.div key="stage-workflow" className="w-full max-w-lg">
                <DemoTodoWorkflow phase={phase} />
              </m.div>
            )}

            {showRun && (
              <m.div key="stage-run" className="w-full max-w-lg">
                <DemoTodoRun phase={phase} />
              </m.div>
            )}

            {showComplete && (
              <m.div key="stage-complete" className="w-full max-w-lg">
                <DemoTodoComplete phase={phase} />
              </m.div>
            )}
          </AnimatePresence>
        </div>
      </m.div>

      {/* Nav controls */}
      <div className="flex w-full items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Button
            isIconOnly
            variant="flat"
            size="sm"
            aria-label="Previous phase"
            onPress={prevPhase}
            isDisabled={PHASE_ORDER.indexOf(phase) <= 0}
            className="rounded-full"
          >
            <ArrowRight02Icon width={18} height={18} className="rotate-180" />
          </Button>
          <Button
            isIconOnly
            variant="flat"
            size="sm"
            aria-label="Next phase"
            onPress={nextPhase}
            isDisabled={PHASE_ORDER.indexOf(phase) >= PHASE_ORDER.length - 1}
            className="rounded-full"
          >
            <ArrowRight02Icon width={18} height={18} />
          </Button>
        </div>
        <Button
          isIconOnly
          variant="flat"
          size="sm"
          aria-label="Restart demo"
          onPress={() => runAnimation()}
          className="rounded-full"
        >
          <RedoIcon width={18} height={18} />
        </Button>
      </div>
    </div>
  );
}
