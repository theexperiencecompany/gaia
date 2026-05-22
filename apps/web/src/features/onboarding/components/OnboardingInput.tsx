/**
 * The bottom composer. Renders one of three modes via a discriminated union:
 * - `qa`: the active question's input (text / Autocomplete / Gmail buttons).
 * - `focus`: a plain text input for the synthetic focus question.
 * - `freeChat`: free chat input for the post-reveal `chat` stage.
 * Auto-focuses the right element via rAF when the active question changes.
 */

import { Autocomplete, AutocompleteItem } from "@heroui/autocomplete";
import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Kbd } from "@heroui/kbd";
import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/modal";
import {
  ArrowUp02Icon,
  Loading03Icon,
  LockPasswordIcon,
  SourceCodeIcon,
} from "@icons";
import Image from "next/image";
import { memo, useEffect, useState } from "react";
import { ChevronRight } from "@/components/shared/icons";
import { RaisedButton } from "@/components/ui/raised-button";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { cn } from "@/lib/utils";

import { FIELD_NAMES, professionOptions, questions } from "../constants";

interface DataPrivacyModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function DataPrivacyModal({ open, onOpenChange }: DataPrivacyModalProps) {
  return (
    <Modal isOpen={open} onOpenChange={onOpenChange} size="sm">
      <ModalContent>
        <ModalHeader className="text-zinc-100">Your data is yours</ModalHeader>
        <ModalBody className="pb-6">
          <div className="space-y-4 text-sm text-zinc-400">
            <div className="flex gap-3">
              <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-emerald-400/10 text-emerald-400">
                <LockPasswordIcon size={16} />
              </div>
              <div>
                <p className="mb-0.5 font-medium text-zinc-200">
                  We never sell your data
                </p>
                <p>
                  Your emails, tasks, and personal info are only used to run
                  GAIA for you. We don't share or sell anything to third
                  parties.
                </p>
              </div>
            </div>
            <div className="flex gap-3">
              <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-blue-400/10 text-blue-400">
                <LockPasswordIcon size={16} />
              </div>
              <div>
                <p className="mb-0.5 font-medium text-zinc-200">
                  Used only for your assistant
                </p>
                <p>
                  Your data is used exclusively to power your personal GAIA
                  experience. Nothing else.
                </p>
              </div>
            </div>
            <div className="flex gap-3">
              <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-violet-400/10 text-violet-400">
                <SourceCodeIcon size={16} />
              </div>
              <div>
                <p className="mb-0.5 font-medium text-zinc-200">
                  Fully open source
                </p>
                <p>
                  Don't take our word for it.{" "}
                  <a
                    href="https://github.com/theexperiencecompany/gaia"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-zinc-200 underline underline-offset-2 transition-colors hover:text-white"
                  >
                    Read the source code on GitHub
                  </a>{" "}
                  and see exactly how your data is handled.
                </p>
              </div>
            </div>
          </div>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}

interface QaModeProps {
  mode: "qa";
  questionIndex: number;
  draftText: string;
  draftProfession: string | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onSubmit: (e: React.FormEvent) => void;
  onInputChange: (value: string) => void;
  onProfessionSelect: (key: React.Key | null) => void;
  onProfessionInputChange: (value: string) => void;
  onGmailSkip: () => void;
}

interface FocusModeProps {
  mode: "focus";
  draftText: string;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onSubmit: (e: React.FormEvent) => void;
  onInputChange: (value: string) => void;
}

interface FreeChatModeProps {
  mode: "freeChat";
  inputRef: React.RefObject<HTMLInputElement | null>;
  freeChatValue: string;
  isSending: boolean;
  onFreeChatChange: (value: string) => void;
  onFreeChatSubmit: (e: React.FormEvent) => void;
}

export type OnboardingInputProps =
  | QaModeProps
  | FocusModeProps
  | FreeChatModeProps;

function OnboardingInputImpl(props: OnboardingInputProps) {
  if (props.mode === "freeChat") return <FreeChatInput {...props} />;
  if (props.mode === "focus") return <FocusInput {...props} />;
  return <QaInput {...props} />;
}

export const OnboardingInput = memo(OnboardingInputImpl);

function FreeChatInput({
  freeChatValue,
  isSending,
  onFreeChatChange,
  onFreeChatSubmit,
}: FreeChatModeProps) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter" || e.shiftKey) return;
    if (!freeChatValue.trim()) return;
    e.preventDefault();
    e.currentTarget.form?.requestSubmit();
  };

  return (
    <form onSubmit={onFreeChatSubmit} className="mx-auto w-full max-w-2xl">
      <div className="relative">
        <Input
          autoFocus
          value={freeChatValue}
          onChange={(e) => onFreeChatChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask me anything..."
          radius="full"
          variant="faded"
          size="lg"
          disabled={isSending}
          classNames={{ inputWrapper: "pr-1" }}
          endContent={
            <Button
              isIconOnly
              type="submit"
              disabled={!freeChatValue.trim() || isSending}
              color={!freeChatValue.trim() || isSending ? "default" : "primary"}
              radius="full"
              aria-label="Send message"
              className={cn(
                isSending && "cursor-wait",
                !freeChatValue.trim() || isSending
                  ? "text-zinc-500"
                  : "text-black",
              )}
            >
              <ArrowUp02Icon />
            </Button>
          }
        />
      </div>
    </form>
  );
}

function FocusInput({
  draftText,
  inputRef,
  onSubmit,
  onInputChange,
}: FocusModeProps) {
  useAutofocus(inputRef, "default");

  return (
    <form onSubmit={onSubmit} className="mx-auto w-full max-w-2xl">
      <div className="relative">
        <TextSendInput
          inputRef={inputRef}
          value={draftText}
          placeholder="Type your answer..."
          onChange={onInputChange}
        />
      </div>
      <PressEnterHint />
    </form>
  );
}

function QaInput(props: QaModeProps) {
  const {
    questionIndex,
    draftText,
    draftProfession,
    inputRef,
    onSubmit,
    onInputChange,
    onProfessionSelect,
    onProfessionInputChange,
    onGmailSkip,
  } = props;
  const currentQuestion =
    questionIndex < questions.length ? questions[questionIndex] : null;
  const targetField =
    currentQuestion?.fieldName === FIELD_NAMES.PROFESSION
      ? "autocomplete"
      : "default";
  useAutofocus(inputRef, targetField);

  if (!currentQuestion) return null;

  return (
    <form onSubmit={onSubmit} className="mx-auto w-full max-w-2xl">
      <div className="relative">
        <QaInputBody
          field={currentQuestion.fieldName}
          questionIndex={questionIndex}
          placeholder={currentQuestion.placeholder}
          draftText={draftText}
          draftProfession={draftProfession}
          inputRef={inputRef}
          onInputChange={onInputChange}
          onProfessionSelect={onProfessionSelect}
          onProfessionInputChange={onProfessionInputChange}
          onGmailSkip={onGmailSkip}
        />
      </div>
      {currentQuestion.fieldName !== FIELD_NAMES.GMAIL && <PressEnterHint />}
    </form>
  );
}

interface QaInputBodyProps {
  field: string;
  questionIndex: number;
  placeholder: string;
  draftText: string;
  draftProfession: string | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onInputChange: (value: string) => void;
  onProfessionSelect: (key: React.Key | null) => void;
  onProfessionInputChange: (value: string) => void;
  onGmailSkip: () => void;
}

function QaInputBody({
  field,
  questionIndex,
  placeholder,
  draftText,
  draftProfession,
  inputRef,
  onInputChange,
  onProfessionSelect,
  onProfessionInputChange,
  onGmailSkip,
}: QaInputBodyProps) {
  if (field === FIELD_NAMES.PROFESSION) {
    return (
      <Autocomplete
        key={`profession-${questionIndex}`}
        inputValue={draftProfession ?? ""}
        onInputChange={onProfessionInputChange}
        onSelectionChange={onProfessionSelect}
        onKeyDown={(e) => {
          if (e.key === "Enter" && draftProfession?.trim()) {
            e.stopPropagation();
          }
        }}
        placeholder="Type or select your profession..."
        variant="faded"
        size="lg"
        radius="full"
        allowsCustomValue
        classNames={{ base: "w-full" }}
      >
        {professionOptions.map((profession) => (
          <AutocompleteItem key={profession.value}>
            {profession.label}
          </AutocompleteItem>
        ))}
      </Autocomplete>
    );
  }

  if (field === FIELD_NAMES.GMAIL) {
    return <GmailInput onGmailSkip={onGmailSkip} />;
  }

  return (
    <TextSendInput
      key={`input-${questionIndex}`}
      inputRef={inputRef}
      value={draftText}
      placeholder={placeholder}
      onChange={onInputChange}
    />
  );
}

function GmailInput({ onGmailSkip }: { onGmailSkip: () => void }) {
  const { connectIntegration } = useIntegrations();
  const [privacyModalOpen, setPrivacyModalOpen] = useState(false);
  const [isConnectingGmail, setIsConnectingGmail] = useState(false);

  return (
    <>
      <div className="mx-auto flex w-full max-w-sm flex-col gap-3">
        <RaisedButton
          color="#00bbff"
          onClick={() => {
            setIsConnectingGmail(true);
            void connectIntegration("gmail");
          }}
          className="w-full text-black!"
          disabled={isConnectingGmail}
        >
          {isConnectingGmail ? (
            <Loading03Icon
              className="animate-spin"
              size={16}
              aria-hidden="true"
            />
          ) : (
            <Image
              src="/images/icons/gmail.svg"
              alt=""
              className="-rotate-12"
              width={16}
              height={16}
              aria-hidden="true"
            />
          )}
          {isConnectingGmail ? "Connecting..." : "Connect Gmail"}
        </RaisedButton>
        <Button
          variant="light"
          onPress={onGmailSkip}
          aria-label="Continue onboarding without connecting Gmail"
          className="text-zinc-400 hover:text-zinc-200"
        >
          Continue without Gmail
        </Button>
        <Button
          variant="light"
          size="sm"
          radius="full"
          onPress={() => setPrivacyModalOpen(true)}
          endContent={<ChevronRight className="size-3" />}
          className="mx-auto w-fit text-xs text-zinc-400 hover:text-zinc-200"
        >
          How we use your data
        </Button>
      </div>
      <DataPrivacyModal
        open={privacyModalOpen}
        onOpenChange={setPrivacyModalOpen}
      />
    </>
  );
}

interface TextSendInputProps {
  inputRef: React.RefObject<HTMLInputElement | null>;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}

function TextSendInput({
  inputRef,
  value,
  placeholder,
  onChange,
}: TextSendInputProps) {
  const disabled = !value.trim();
  return (
    <Input
      ref={inputRef}
      value={value}
      radius="full"
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      variant="faded"
      size="lg"
      classNames={{ inputWrapper: "pr-1" }}
      endContent={
        <Button
          isIconOnly
          type="submit"
          disabled={disabled}
          color={disabled ? "default" : "primary"}
          radius="full"
          aria-label="Send message"
          className={cn(disabled ? "text-zinc-500" : "text-black")}
        >
          <ArrowUp02Icon />
        </Button>
      }
    />
  );
}

function PressEnterHint() {
  return (
    <p className="mt-2 flex items-center justify-center space-x-1 text-center text-xs text-zinc-300">
      <span>Press</span>
      <Kbd keys={"enter"} />
      <span>to continue</span>
    </p>
  );
}

function useAutofocus(
  inputRef: React.RefObject<HTMLInputElement | null>,
  target: "default" | "autocomplete",
) {
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      if (target === "autocomplete") {
        const el = document.querySelector(
          '[data-slot="input"]',
        ) as HTMLInputElement | null;
        el?.focus();
      } else {
        inputRef.current?.focus();
      }
    });
    return () => cancelAnimationFrame(id);
  }, [target, inputRef]);
}
