/**
 * The bottom composer for the two onboarding questions. Two modes via a
 * discriminated union:
 * - `profession`: Q1's single-select Autocomplete.
 * - `needs`: Q2's multi-select chip grid plus its Continue button.
 * Auto-focuses the right element via rAF when the active question changes.
 */

import { Autocomplete, AutocompleteItem } from "@heroui/autocomplete";
import { memo, useEffect } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { cn } from "@/lib/utils";

import { needOptions, professionOptions } from "../constants";
import { NEEDS_HINT } from "../constants/messages";
import { OnboardingCTAButton } from "./OnboardingCTAButton";

interface ProfessionModeProps {
  mode: "profession";
  draftProfession: string | null;
  onProfessionSelect: (key: React.Key | null) => void;
  onProfessionInputChange: (value: string) => void;
}

interface NeedsModeProps {
  mode: "needs";
  selectedNeeds: string[];
  canContinue: boolean;
  onToggleNeed: (value: string) => void;
  onContinue: () => void;
}

export type OnboardingInputProps = ProfessionModeProps | NeedsModeProps;

function OnboardingInputImpl(props: OnboardingInputProps) {
  if (props.mode === "needs") return <NeedsInput {...props} />;
  return <ProfessionInput {...props} />;
}

export const OnboardingInput = memo(OnboardingInputImpl);

function ProfessionInput({
  draftProfession,
  onProfessionSelect,
  onProfessionInputChange,
}: ProfessionModeProps) {
  useAutofocusAutocomplete();

  return (
    <div className="mx-auto w-full max-w-2xl">
      <Autocomplete
        inputValue={draftProfession ?? ""}
        onInputChange={onProfessionInputChange}
        onSelectionChange={onProfessionSelect}
        placeholder="Select what you do..."
        aria-label="What do you do?"
        variant="faded"
        size="lg"
        radius="full"
        classNames={{ base: "w-full" }}
      >
        {professionOptions.map((profession) => (
          <AutocompleteItem key={profession.value}>
            {profession.label}
          </AutocompleteItem>
        ))}
      </Autocomplete>
    </div>
  );
}

function NeedsInput({
  selectedNeeds,
  canContinue,
  onToggleNeed,
  onContinue,
}: NeedsModeProps) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center gap-3">
      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
        {needOptions.map((option) => {
          const isSelected = selectedNeeds.includes(option.value);
          return (
            <RaisedButton
              key={option.value}
              color={isSelected ? "#00bbff" : "black"}
              aria-pressed={isSelected}
              onClick={() => onToggleNeed(option.value)}
              className={cn(
                "h-auto w-full flex-col items-start gap-0 px-3 py-2 text-left",
                isSelected && "text-black!",
              )}
            >
              <span className="font-medium text-sm">{option.label}</span>
              <span
                className={cn(
                  "text-xs",
                  isSelected ? "text-black/70" : "text-zinc-400",
                )}
              >
                {option.sub}
              </span>
            </RaisedButton>
          );
        })}
      </div>
      <p className="text-xs text-zinc-400">{NEEDS_HINT}</p>
      <OnboardingCTAButton disabled={!canContinue} onClick={onContinue}>
        Continue
      </OnboardingCTAButton>
    </div>
  );
}

function useAutofocusAutocomplete() {
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      const el = document.querySelector(
        '[data-slot="input"]',
      ) as HTMLInputElement | null;
      el?.focus();
    });
    return () => cancelAnimationFrame(id);
  }, []);
}
