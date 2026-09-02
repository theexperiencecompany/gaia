/**
 * The user's side of the two onboarding questions: a right-aligned row of
 * tinted icon chips where their reply bubble will land, plus Continue. Two
 * modes via a discriminated union:
 * - `profession`: Q1's single-select (picking one replaces the current pick).
 * - `needs`: Q2's multi-select.
 * Either way the answer is only committed when Continue is pressed. Both
 * questions end in a catch-all chip that opens a small text field, so an
 * answer the list does not have is still their own words.
 */

import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import * as m from "motion/react-m";
import { memo, useState } from "react";

import {
  isListedProfession,
  needOptions,
  OTHER_NEED,
  OTHER_NEED_MAX_LENGTH,
  OTHER_NEED_OPTION,
  OTHER_PROFESSION,
  PROFESSION_MAX_LENGTH,
  professionOptions,
} from "../constants";
import { EASE_OUT_QUART } from "../constants/motion";
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
  otherNeed: string;
  canContinue: boolean;
  onToggleNeed: (value: string) => void;
  onOtherNeedChange: (value: string) => void;
  onContinue: () => void;
}

export type OnboardingInputProps = ProfessionModeProps | NeedsModeProps;

function OnboardingInputImpl(props: OnboardingInputProps) {
  if (props.mode === "needs") return <NeedsInput {...props} />;
  return <ProfessionInput {...props} />;
}

export const OnboardingInput = memo(OnboardingInputImpl);

const REPLY_WRAPPER_CLASS =
  "ml-auto flex w-full max-w-xl flex-col items-end gap-3 pt-3";

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
    <div className={REPLY_WRAPPER_CLASS}>
      <OptionChips
        label="What do you do?"
        options={professionOptions}
        isSelected={(value) =>
          value === OTHER_PROFESSION ? isOther : value === draftProfession
        }
        onSelect={onSelectProfession}
      />
      {isOther && (
        <OwnWordsInput
          label="Your job, in your words"
          placeholder="What do you do?"
          maxLength={PROFESSION_MAX_LENGTH}
          value={customText}
          onValueChange={(text) =>
            onSelectProfession(text.trim() ? text : OTHER_PROFESSION)
          }
          onSubmit={() => {
            if (draftProfession) onContinue();
          }}
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
  otherNeed,
  canContinue,
  onToggleNeed,
  onOtherNeedChange,
  onContinue,
}: NeedsModeProps) {
  const selected = new Set(selectedNeeds);
  // The field stays open while they type; un-picking the chip also clears the
  // text, so a closed field never submits words they can no longer see.
  const [otherOpen, setOtherOpen] = useState(otherNeed !== "");

  const handleSelect = (value: string) => {
    if (value !== OTHER_NEED) {
      onToggleNeed(value);
      return;
    }
    if (otherOpen) onOtherNeedChange("");
    setOtherOpen(!otherOpen);
  };

  return (
    <div className={REPLY_WRAPPER_CLASS}>
      <OptionChips
        label="What does a normal week look like?"
        options={[...needOptions, OTHER_NEED_OPTION]}
        isSelected={(value) =>
          value === OTHER_NEED ? otherOpen : selected.has(value)
        }
        onSelect={handleSelect}
      />
      {otherOpen && (
        <OwnWordsInput
          label="Something else, in your words"
          placeholder="Say it in a few words"
          maxLength={OTHER_NEED_MAX_LENGTH}
          value={otherNeed}
          onValueChange={onOtherNeedChange}
          onSubmit={() => {
            if (canContinue) onContinue();
          }}
        />
      )}
      <OnboardingCTAButton disabled={!canContinue} onClick={onContinue}>
        Continue
      </OnboardingCTAButton>
    </div>
  );
}

interface OwnWordsInputProps {
  label: string;
  placeholder: string;
  maxLength: number;
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: () => void;
}

/** How close to the cap the text has to get before we start counting out loud.
 * Showing "0/50" from the first keystroke turns a free-text answer into a form
 * field; showing nothing at all is why the cap felt like a broken keyboard. */
const COUNTER_REVEAL_WINDOW = 10;

/** The small free-text field a catch-all chip opens. Enter submits the turn. */
function OwnWordsInput({
  label,
  placeholder,
  maxLength,
  value,
  onValueChange,
  onSubmit,
}: OwnWordsInputProps) {
  // `maxLength` stops the keystroke silently, so the only way a user learns
  // the cap exists is if we say so — quietly near the end, plainly at it.
  const remaining = maxLength - value.length;
  const isAtLimit = remaining <= 0;
  const showsCounter = remaining <= COUNTER_REVEAL_WINDOW;

  return (
    <Input
      aria-label={label}
      placeholder={placeholder}
      maxLength={maxLength}
      value={value}
      onValueChange={onValueChange}
      isInvalid={isAtLimit}
      description={
        showsCounter && !isAtLimit ? `${value.length}/${maxLength}` : undefined
      }
      errorMessage={
        isAtLimit ? `Keep it under ${maxLength} characters` : undefined
      }
      // The counter and message sit under the field, so the row can grow taller
      // but never wider — `max-w-56` above stays the field's whole width.
      classNames={{ description: "text-tiny", errorMessage: "text-tiny" }}
      onKeyDown={(event) => {
        // Enter also confirms a candidate in CJK input methods; submitting
        // then would send half a word.
        if (event.nativeEvent.isComposing) return;
        if (event.key === "Enter") onSubmit();
      }}
      variant="flat"
      size="sm"
      radius="lg"
      className="max-w-56"
      autoFocus
    />
  );
}

interface OptionChipsProps {
  label: string;
  options: { value: string; label: string }[];
  isSelected: (value: string) => boolean;
  onSelect: (value: string) => void;
}

const CHIP_STAGGER_SECONDS = 0.035;

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
      {options.map((option, index) => {
        const selected = isSelected(option.value);
        const { icon: Icon, tint } = OPTION_STYLE[option.value];
        return (
          // Chips arrive one after another, like a reply being typed out, and
          // give a little under the finger when pressed.
          <m.div
            key={option.value}
            initial={{ opacity: 0, y: 6, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            whileTap={{ scale: 0.95 }}
            transition={{
              delay: index * CHIP_STAGGER_SECONDS,
              duration: 0.3,
              ease: EASE_OUT_QUART,
            }}
          >
            <Chip
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
          </m.div>
        );
      })}
    </fieldset>
  );
}
