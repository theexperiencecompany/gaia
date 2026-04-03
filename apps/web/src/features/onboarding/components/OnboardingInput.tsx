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
import { useEffect, useState } from "react";
import { ChevronRight } from "@/components/shared/icons";
import { RaisedButton } from "@/components/ui/raised-button";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { cn } from "@/lib/utils";

import { FIELD_NAMES, professionOptions, questions } from "../constants";
import type { OnboardingState } from "../types";

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

interface OnboardingInputProps {
  onboardingState: OnboardingState;
  onSubmit: (e: React.FormEvent) => void;
  onInputChange: (value: string) => void;
  onProfessionSelect: (professionKey: React.Key | null) => void;
  onProfessionInputChange: (value: string) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onGmailSkip?: () => void;
  /** When true, renders a plain text input instead of the Gmail buttons (focus question phase) */
  isFocusPending?: boolean;
  /** When true, renders a plain free-chat input instead of question-driven UI */
  isFreeChatMode?: boolean;
  freeChatValue?: string;
  onFreeChatChange?: (value: string) => void;
  onFreeChatSubmit?: (e: React.FormEvent) => void;
  isSending?: boolean;
}

export const OnboardingInput = ({
  onboardingState,
  onSubmit,
  onInputChange,
  onProfessionSelect,
  onProfessionInputChange,
  inputRef,
  onGmailSkip,
  isFocusPending = false,
  isFreeChatMode = false,
  freeChatValue = "",
  onFreeChatChange,
  onFreeChatSubmit,
  isSending = false,
}: OnboardingInputProps) => {
  const { connectIntegration } = useIntegrations();
  const [privacyModalOpen, setPrivacyModalOpen] = useState(false);
  const [isConnectingGmail, setIsConnectingGmail] = useState(false);

  const currentQuestion =
    onboardingState.currentQuestionIndex < questions.length
      ? questions[onboardingState.currentQuestionIndex]
      : null;

  // Focus the appropriate input when question changes (Q&A phase only)
  useEffect(() => {
    if (isFreeChatMode) return;
    if (isFocusPending || !onboardingState.hasAnsweredCurrentQuestion) {
      setTimeout(() => {
        if (currentQuestion?.fieldName === FIELD_NAMES.PROFESSION) {
          const autocompleteInput = document.querySelector(
            '[data-slot="input"]',
          ) as HTMLInputElement;
          if (autocompleteInput) {
            autocompleteInput.focus();
          }
        } else {
          inputRef.current?.focus();
        }
      }, 500);
    }
  }, [
    isFreeChatMode,
    isFocusPending,
    onboardingState.hasAnsweredCurrentQuestion,
    currentQuestion?.fieldName,
    inputRef,
  ]);

  // Free-chat mode: plain text input for post-reveal conversation
  if (isFreeChatMode) {
    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && !e.shiftKey && freeChatValue.trim()) {
        e.preventDefault();
        onFreeChatSubmit?.(e as unknown as React.FormEvent);
      }
    };

    return (
      <form onSubmit={onFreeChatSubmit} className="mx-auto w-full max-w-2xl">
        <div className="relative">
          <Input
            autoFocus
            value={freeChatValue}
            onChange={(e) => onFreeChatChange?.(e.target.value)}
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
                color={
                  !freeChatValue.trim() || isSending ? "default" : "primary"
                }
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

  if (onboardingState.isProcessingPhase) return null;
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

      case FIELD_NAMES.GMAIL:
        if (!isFocusPending)
          return (
            <>
              <div className="flex flex-col gap-3">
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
                      className="[animation:fadeIn_150ms_ease-out_forwards,spin_0.8s_linear_infinite]"
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
                <button
                  type="button"
                  onClick={onGmailSkip}
                  aria-label="Continue onboarding without connecting Gmail"
                  className="cursor-pointer text-center text-sm text-zinc-500 transition-colors hover:text-zinc-300"
                >
                  Continue without Gmail
                </button>
                <button
                  type="button"
                  onClick={() => setPrivacyModalOpen(true)}
                  className="flex cursor-pointer items-center justify-center gap-1 text-xs text-zinc-600 transition-colors hover:text-zinc-400"
                >
                  How we use your data
                  <ChevronRight className="size-3" />
                </button>
              </div>
              <DataPrivacyModal
                open={privacyModalOpen}
                onOpenChange={setPrivacyModalOpen}
              />
            </>
          );
        return null;

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
                disabled={!onboardingState.currentInputs.text.trim()}
                color={
                  !onboardingState.currentInputs.text.trim()
                    ? "default"
                    : "primary"
                }
                radius="full"
                aria-label="Send message"
                className={cn(
                  !onboardingState.currentInputs.text.trim()
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
      {currentQuestion.fieldName !== FIELD_NAMES.GMAIL && (
        <p className="mt-2 flex items-center justify-center space-x-1 text-center text-xs text-zinc-500">
          <span>Press</span>
          <Kbd keys={"enter"} />
          <span>to continue</span>
        </p>
      )}
    </form>
  );
};
