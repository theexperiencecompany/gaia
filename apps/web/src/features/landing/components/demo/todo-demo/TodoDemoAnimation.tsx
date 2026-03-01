"use client";

import { AnimatePresence, m, useInView } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  DemoBackground,
  DemoNavControls,
} from "@/features/landing/components/demo/DemoAnimationLayout";
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
      <DemoBackground ease={tdEase}>
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
      </DemoBackground>

      <DemoNavControls
        phaseIndex={PHASE_ORDER.indexOf(phase)}
        phaseCount={PHASE_ORDER.length}
        onPrev={prevPhase}
        onNext={nextPhase}
        onRestart={runAnimation}
      />
    </div>
  );
}
