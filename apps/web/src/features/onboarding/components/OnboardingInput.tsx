import { Autocomplete, AutocompleteItem } from "@heroui/autocomplete";
import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Kbd } from "@heroui/kbd";
import { useEffect } from "react";

import { ArrowUp02Icon } from "@/icons";
import { cn } from "@/lib/utils";

import { FIELD_NAMES, professionOptions, questions } from "../constants";
import type { OnboardingState } from "../types";

interface OnboardingInputProps {
  onboardingState: OnboardingState;
  onSubmit: (e: React.FormEvent) => void;
  onInputChange: (value: string) => void;
  onProfessionSelect: (professionKey: React.Key | null) => void;
  onProfessionInputChange: (value: string) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
}

export const OnboardingInput = ({
  onboardingState,
  onSubmit,
  onInputChange,
  onProfessionSelect,
  onProfessionInputChange,
  inputRef,
}: OnboardingInputProps) => {
  const currentQuestion =
    onboardingState.currentQuestionIndex < questions.length
      ? questions[onboardingState.currentQuestionIndex]
      : null;

  // Focus the appropriate input when question changes
  useEffect(() => {
    if (
      !onboardingState.isProcessing &&
      !onboardingState.hasAnsweredCurrentQuestion
    ) {
      setTimeout(() => {
        if (currentQuestion?.fieldName === FIELD_NAMES.PROFESSION) {
          // Focus the autocomplete input
          const autocompleteInput = document.querySelector(
            '[data-slot="input"]',
          ) as HTMLInputElement;
          if (autocompleteInput) {
            autocompleteInput.focus();
          }
        } else {
          // Focus regular input
          inputRef.current?.focus();
        }
      }, 500);
    }
  }, [
    onboardingState.isProcessing,
    onboardingState.hasAnsweredCurrentQuestion,
    currentQuestion?.fieldName,
    inputRef,
  ]);

  if (!currentQuestion) return null;

  const renderInput = () => {
    switch (currentQuestion.fieldName) {
      case FIELD_NAMES.PROFESSION:
        return (
          <Autocomplete
            key={`profession-${onboardingState.currentQuestionIndex}`}
            inputValue={onboardingState.currentInputs.selectedProfession || ""}
            onInputChange={onProfessionInputChange}
            onSelectionChange={onProfessionSelect}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                onboardingState.currentInputs.selectedProfession?.trim()
              ) {
                e.stopPropagation();
              }
            }}
            placeholder="Type or select your profession..."
            variant="faded"
            size="lg"
            radius="full"
            allowsCustomValue
            classNames={{
              base: "w-full",
            }}
          >
            {professionOptions.map((profession) => (
              <AutocompleteItem key={profession.value}>
                {profession.label}
              </AutocompleteItem>
            ))}
          </Autocomplete>
        );

      default:
        return (
          <Input
            key={`input-${onboardingState.currentQuestionIndex}`}
            ref={inputRef}
            value={onboardingState.currentInputs.text}
            radius="full"
            onChange={(e) => onInputChange(e.target.value)}
            placeholder={currentQuestion.placeholder}
            variant="faded"
            size="lg"
            classNames={{ inputWrapper: "pr-1" }}
            endContent={
              <Button
                isIconOnly
                type="submit"
                disabled={
                  !onboardingState.currentInputs.text.trim() ||
                  onboardingState.isProcessing
                }
                color={
                  !onboardingState.currentInputs.text.trim() ||
                  onboardingState.isProcessing
                    ? "default"
                    : "primary"
                }
                radius="full"
                aria-label="Send message"
                className={cn(
                  onboardingState.isProcessing && "cursor-wait",
                  !onboardingState.currentInputs.text.trim() ||
                    onboardingState.isProcessing
                    ? "text-zinc-500"
                    : "text-black",
                )}
              >
                <ArrowUp02Icon />
              </Button>
            }
          />
        );
    }
  };

  return (
    <form onSubmit={onSubmit} className="mx-auto w-full max-w-2xl">
      <div className="relative">{renderInput()}</div>
      <p className="mt-2 flex items-center justify-center space-x-1 text-center text-xs text-zinc-500">
        <span>Press</span>
        <Kbd keys={"enter"} />
        <span>to continue</span>
      </p>
    </form>
  );
};
