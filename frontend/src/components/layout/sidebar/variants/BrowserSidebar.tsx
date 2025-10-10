"use client";

import { Button } from "@heroui/button";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Brain,
  Globe,
  X,
  Zap,
} from "lucide-react";
import { useEffect } from "react";

import { Message } from "@/app/(main)/browser/page";
import { ScrollArea } from "@/components/ui/shadcn/scroll-area";

export const BrowserSidebar = ({
  isOpen,
  onToggle,
  steps,
  currentStepIndex,
  setCurrentStepIndex,
}: {
  isOpen: boolean;
  onToggle: () => void;
  steps: Message[];
  currentStepIndex: number;
  setCurrentStepIndex: (index: number) => void;
}) => {
  const validSteps = steps.filter(
    (step) =>
      step.role === "assistant" &&
      step.stepData &&
      (step.stepData.url || step.stepData.thoughts || step.stepData.actions),
  );

  // Update current step whenever valid steps change to show the latest step
  useEffect(() => {
    if (validSteps.length > 0) {
      setCurrentStepIndex(validSteps.length - 1);
    }
  }, [validSteps.length, setCurrentStepIndex]);

  const currentStep = validSteps[currentStepIndex];

  const goToPreviousStep = () => {
    if (currentStepIndex > 0) {
      setCurrentStepIndex(currentStepIndex - 1);
    }
  };

  const goToNextStep = () => {
    if (currentStepIndex < validSteps.length - 1) {
      setCurrentStepIndex(currentStepIndex + 1);
    }
  };

  if (!currentStep || validSteps.length === 0) {
    return null;
  }

  return (
    <div
      className={`relative h-full shrink-0 overflow-hidden rounded-2xl border-l border-zinc-800 bg-zinc-900 shadow-xl transition-all duration-300 ease-in-out ${
        isOpen ? "w-[40vw]" : "w-0"
      }`}
    >
      {/* Toggle button for sidebar */}
      <button
        onClick={onToggle}
        className="absolute top-1/2 -left-12 z-10 flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-l-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
      >
        {isOpen ? <ArrowRight size={20} /> : <ArrowLeft size={20} />}
      </button>

      {/* sidebar Content */}
      <div className="flex h-full flex-col overflow-hidden">
        {/* Header */}
        <div className="flex w-full items-center justify-between gap-3 border-b border-zinc-800 bg-zinc-900 p-4">
          <div className="grid w-full grid-cols-[auto_1fr] items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="text-sm text-zinc-300">
                Step {currentStepIndex + 1} of {validSteps.length}
              </div>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
              <div
                className="h-full bg-primary transition-all duration-300 ease-in-out"
                style={{
                  width: `${((currentStepIndex + 1) / validSteps.length) * 100}%`,
                }}
              />
            </div>
          </div>

          <Button
            isIconOnly
            size="sm"
            variant="light"
            className="rounded-full"
            onPress={onToggle}
          >
            <X size={18} />
          </Button>
        </div>

        {/* Content */}
        <ScrollArea className="flex-1">
          <div className="space-y-2 p-4">
            {/* URL display */}
            {currentStep.stepData?.url && (
              <div className="flex items-center gap-2 rounded-lg text-sm">
                <Button
                  size="sm"
                  variant="flat"
                  as="a"
                  href={currentStep.stepData.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {currentStep.stepData.url}

                  <ArrowUpRight className="h-4 w-4" />
                </Button>
              </div>
            )}

            {/* AI thoughts */}
            {currentStep.stepData?.thoughts && (
              <div className="space-y-3 rounded-lg bg-zinc-800 p-4">
                <div className="mb-1 flex items-center gap-2 border-b border-zinc-700 pb-2 text-zinc-300">
                  <Brain className="h-5 w-5 text-indigo-400" />
                  <div className="font-medium">AI Analysis</div>
                </div>

                {/* Evaluation or Previous Goal Evaluation */}
                {(currentStep.stepData.thoughts.evaluation ||
                  currentStep.stepData.thoughts.evaluation_previous_goal) && (
                  <div className="space-y-1">
                    <div className="text-sm font-medium text-primary">
                      Evaluation:
                    </div>
                    <div className="text-sm text-zinc-300">
                      {currentStep.stepData.thoughts.evaluation ||
                        currentStep.stepData.thoughts.evaluation_previous_goal}
                    </div>
                  </div>
                )}

                {/* memory */}
                {currentStep.stepData.thoughts.memory && (
                  <div className="space-y-1">
                    <div className="text-sm font-medium text-blue-400">
                      Memory:
                    </div>
                    <div className="text-sm text-zinc-300">
                      {currentStep.stepData.thoughts.memory}
                    </div>
                  </div>
                )}

                {/* Next Goal */}
                {currentStep.stepData.thoughts.next_goal && (
                  <div className="space-y-1">
                    <div className="text-sm font-medium text-green-400">
                      Next Goal:
                    </div>
                    <div className="text-sm text-zinc-300">
                      {currentStep.stepData.thoughts.next_goal}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Actions */}
            {currentStep.stepData?.actions &&
              currentStep.stepData.actions.length > 0 && (
                <div className="space-y-3 rounded-lg bg-zinc-800 p-4">
                  <div className="mb-1 flex items-center gap-2 border-b border-zinc-700 pb-2 text-zinc-300">
                    <Zap className="h-5 w-5 text-yellow-400" />
                    <div className="font-medium">Actions Taken</div>
                  </div>
                  <ul className="space-y-2">
                    {currentStep.stepData.actions.map((action, index) => (
                      <li
                        key={index}
                        className="flex items-center gap-2 rounded-md bg-zinc-700/60 p-2 text-sm"
                      >
                        {action.navigate && (
                          <>
                            <ArrowUpRight className="h-4 w-4 shrink-0 text-blue-400" />
                            <span>Navigate to: </span>
                            <span className="truncate text-blue-400 underline">
                              {action.navigate.url}
                            </span>
                          </>
                        )}
                        {action.click && (
                          <>
                            <div className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-zinc-500 text-[10px]">
                              C
                            </div>
                            <span>Click: </span>
                            <code className="rounded bg-zinc-600 px-1 py-0.5 text-xs">
                              {action.click.selector}
                            </code>
                          </>
                        )}
                        {action.search_google && (
                          <>
                            <Globe className="h-4 w-4 shrink-0 text-blue-400" />
                            <span>Search: </span>
                            <span className="italic">
                              "{action.search_google.query}"
                            </span>
                          </>
                        )}
                        {action.go_to_url && (
                          <>
                            <ArrowUpRight className="h-4 w-4 shrink-0 text-blue-400" />
                            <span>Go to URL: </span>
                            <span className="truncate text-blue-400 underline">
                              {action.go_to_url.url}
                            </span>
                          </>
                        )}
                        {action.done && (
                          <>
                            <span className="shrink-0 text-green-400">✓</span>
                            <span>{action.done.text}</span>
                          </>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
          </div>
        </ScrollArea>

        {/* Navigation footer */}
        <div className="border-t border-zinc-800 bg-zinc-900 p-4">
          <div className="flex justify-between">
            <Button
              variant="flat"
              onPress={goToPreviousStep}
              isDisabled={currentStepIndex === 0}
              startContent={<ArrowLeft className="h-4 w-4" />}
              size="sm"
            >
              Previous
            </Button>
            <Button
              variant="flat"
              onPress={goToNextStep}
              isDisabled={currentStepIndex === validSteps.length - 1}
              endContent={<ArrowRight className="h-4 w-4" />}
              size="sm"
              color="primary"
            >
              Next
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};
