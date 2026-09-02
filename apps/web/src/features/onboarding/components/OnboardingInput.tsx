/**
 * The user's side of the two onboarding questions: a right-aligned row of
 * emoji chips where their reply bubble will land, plus Continue. Two modes
 * via a discriminated union:
 * - `profession`: Q1's single-select (picking one replaces the current pick).
 * - `needs`: Q2's multi-select.
 * Either way the answer is only committed when Continue is pressed.
 */

import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { memo } from "react";

import {
  isListedProfession,
  needOptions,
  OTHER_PROFESSION,
  professionOptions,
} from "../constants";
import { NEEDS_HINT } from "../constants/messages";
import { OPTION_STYLE } from "../constants/optionStyle";
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
  // "Other" is a chip and a text field: the chip opens the field, and whatever
  // is typed becomes the draft, so a job the list does not have is still
  // their own words rather than a compromise chip.
  const isOther =
    draftProfession !== null && !isListedProfession(draftProfession);
  const customText =
    isOther && draftProfession !== OTHER_PROFESSION ? draftProfession : "";

  return (
    <div className="flex w-full flex-col items-end gap-3 pt-3">
      <OptionChips
        label="What do you do?"
        options={professionOptions}
        isSelected={(value) =>
          value === OTHER_PROFESSION ? isOther : value === draftProfession
        }
        onSelect={onSelectProfession}
      />
      {isOther && (
        <Input
          aria-label="Your job, in your words"
          placeholder="What do you do?"
          value={customText}
          onValueChange={(text) =>
            onSelectProfession(text.trim() ? text : OTHER_PROFESSION)
          }
          variant="flat"
          size="lg"
          radius="full"
          className="max-w-xs"
          autoFocus
        />
      )}
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
        const { icon: Icon, tint } = OPTION_STYLE[option.value];
        return (
          <Chip
            key={option.value}
            as="button"
            type="button"
            size="lg"
            radius="full"
            variant="flat"
            aria-pressed={selected}
            onClick={() => onSelect(option.value)}
            // One pastel per option, on the fill, the text and the icon; the
            // fill goes solid when picked. Founder's call, not a theme override.
            classNames={{
              base: `cursor-pointer ${selected ? tint.active : tint.idle}`,
              content: "font-medium",
            }}
            startContent={<Icon className="size-4 shrink-0" />}
          >
            {option.label}
          </Chip>
        );
      })}
    </fieldset>
  );
}
