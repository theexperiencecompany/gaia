"use client";

import { Chip } from "@heroui/chip";
import { AnimatePresence, motion } from "framer-motion";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const wfEase = [0.32, 0.72, 0, 1] as const;

interface DemoStep {
  id: string;
  title: string;
  description: string;
  category: string;
}

interface DemoWorkflowStepsProps {
  steps: DemoStep[];
  visibleCount: number;
}

export default function DemoWorkflowSteps({
  steps,
  visibleCount,
}: DemoWorkflowStepsProps) {
  const visible = steps.slice(0, visibleCount);

  return (
    <div className="relative pb-2">
      {/* Timeline line */}
      {visible.length > 1 && (
        <motion.div
          className="absolute left-[11px] top-3 w-px bg-linear-to-b from-primary via-primary/80 to-transparent"
          initial={{ height: 0 }}
          animate={{ height: "calc(100% - 24px)" }}
          transition={{ duration: 0.4, ease: wfEase }}
        />
      )}

      <div className="space-y-5">
        <AnimatePresence>
          {visible.map((step, index) => (
            <motion.div
              key={step.id}
              initial={{ opacity: 0, y: 10, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{
                type: "spring",
                stiffness: 400,
                damping: 30,
                delay: index * 0.1,
              }}
              className="relative flex items-start gap-4"
            >
              {/* Numbered dot */}
              <div className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-primary bg-primary/10 backdrop-blur-sm">
                <span className="text-xs font-semibold text-primary">
                  {index + 1}
                </span>
              </div>

              {/* Content */}
              <div className="flex-1 space-y-1">
                <Chip
                  radius="md"
                  variant="flat"
                  size="sm"
                  className="h-auto py-4! pl-2 space-x-1 text-xs"
                  startContent={
                    <div className="min-w-fit">
                      {getToolCategoryIcon(step.category, {
                        size: 17,
                        width: 17,
                        height: 17,
                        showBackground: false,
                      })}
                    </div>
                  }
                >
                  {step.category
                    .replaceAll("_", " ")
                    .replace(/\b\w/g, (c) => c.toUpperCase())}
                </Chip>
                <p className="text-sm font-medium leading-snug text-zinc-200">
                  {step.title}
                </p>
                <p className="text-xs leading-snug text-zinc-500">
                  {step.description}
                </p>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
