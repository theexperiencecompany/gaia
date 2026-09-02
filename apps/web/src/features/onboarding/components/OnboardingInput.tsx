/**
 * The user's side of the two onboarding questions: a right-aligned row of
 * emoji chips where their reply bubble will land, plus Continue. Two modes
 * via a discriminated union:
 * - `profession`: Q1's single-select (picking one replaces the current pick).
 * - `needs`: Q2's multi-select.
 * Either way the answer is only committed when Continue is pressed.
 */

import { Chip } from "@heroui/chip";
import Image from "next/image";
import { memo } from "react";

import { needOptions, professionOptions } from "../constants";
import { NEEDS_HINT } from "../constants/messages";
import { OPTION_EMOJI } from "../constants/optionEmoji";
import { OnboardingCTAButton } from "./OnboardingCTAButton";

interface ProfessionModeProps {
  mode: "profession";
  draftProfession: string | null;
  onSelectProfession: (value: string) => void;
  onContinue: () => void;
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
  onSelectProfession,
  onContinue,
}: ProfessionModeProps) {
  return (
    <div className="flex w-full flex-col items-end gap-3 pt-3">
      <OptionChips
        label="What do you do?"
        options={professionOptions}
        isSelected={(value) => value === draftProfession}
        onSelect={onSelectProfession}
      />
      <OnboardingCTAButton disabled={!draftProfession} onClick={onContinue}>
        Continue
      </OnboardingCTAButton>
    </div>
  );
}

function NeedsInput({
  selectedNeeds,
  canContinue,
  onToggleNeed,
  onContinue,
}: NeedsModeProps) {
  const selected = new Set(selectedNeeds);

  return (
    <div className="flex w-full flex-col items-end gap-3 pt-3">
      <OptionChips
        label="What do you want help with?"
        options={needOptions}
        isSelected={(value) => selected.has(value)}
        onSelect={onToggleNeed}
      />
      <p className="text-xs text-zinc-400">{NEEDS_HINT}</p>
      <OnboardingCTAButton disabled={!canContinue} onClick={onContinue}>
        Continue
      </OnboardingCTAButton>
    </div>
  );
}

interface OptionChipsProps {
  label: string;
  options: { value: string; label: string }[];
  isSelected: (value: string) => boolean;
  onSelect: (value: string) => void;
}

function OptionChips({
  label,
  options,
  isSelected,
  onSelect,
}: OptionChipsProps) {
  return (
    // <fieldset> is the semantic grouping element; `min-w-0` defeats its UA
    // `min-inline-size: min-content`, which would otherwise stop the pills wrapping.
    <fieldset
      aria-label={label}
      className="flex w-full min-w-0 flex-wrap justify-end gap-2"
    >
      {options.map((option) => {
        const selected = isSelected(option.value);
        return (
          <Chip
            key={option.value}
            as="button"
            type="button"
            size="lg"
            radius="full"
            variant={selected ? "solid" : "flat"}
            color={selected ? "primary" : "default"}
            aria-pressed={selected}
            onClick={() => onSelect(option.value)}
            className="cursor-pointer"
            startContent={
              <Image
                src={OPTION_EMOJI[option.value]}
                alt=""
                width={22}
                height={22}
              />
            }
          >
            {option.label}
          </Chip>
        );
      })}
    </fieldset>
  );
}
