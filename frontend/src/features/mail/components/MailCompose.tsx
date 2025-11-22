import { Button } from "@heroui/button";
import { ButtonGroup } from "@heroui/button";
import { Input } from "@heroui/input";
import { EditorContent } from "@tiptap/react";
import { TagInput } from "emblor";
import Image from "next/image";
import { Drawer } from "vaul";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useUser } from "@/features/auth/hooks/useUser";
import { useEmailComposition } from "@/features/mail/hooks/useEmailComposition";
import { AlertCircleIcon, ArrowDown01Icon, Tick02Icon } from "@/icons";
import { AiSearch02Icon, BrushIcon, Sent02Icon, SentIcon } from "@/icons";

// import { MenuBar } from "@/features/notes/components/NotesMenuBar";
import { Button as ShadcnButton } from "../../../components/ui/button";
import { AiSearchModal } from "./AiSearchModal";

interface MailComposeProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function MailCompose({ open, onOpenChange }: MailComposeProps) {
  const user = useUser();
  const { formState, uiState, actions, editor, options } =
    useEmailComposition();

  // Destructure state and actions for easier access
  const {
    toEmails,
    subject,
    body: _body,
    prompt,
    writingStyle,
    contentLength,
    clarityOption,
  } = formState;

  const { loading, error, isAiModalOpen, activeTagIndex } = uiState;

  const {
    setToEmails,
    setSubject,
    setPrompt,
    setWritingStyle,
    setContentLength,
    setClarityOption,
    setIsAiModalOpen,
    setActiveTagIndex,
    handleAiSelect,
    handleAskGaia,
    handleAskGaiaKeyPress,
  } = actions;

  const { writingStyles, contentLengthOptions, clarityOptions } = options;

  // Remaining original logic that doesn't belong in the hook

  return (
    <>
      <Drawer.Root open={open} onOpenChange={onOpenChange} direction="right">
        <Drawer.Portal>
          <Drawer.Overlay
            className={`fixed inset-0 bg-black/40 backdrop-blur-md ${
              isAiModalOpen ? "pointer-events-auto" : "pointer-events-none"
            }`}
          />
          <Drawer.Content
            className="fixed right-0 bottom-0 z-10 flex min-h-[60vh] w-[50vw] flex-col gap-2 rounded-tl-xl bg-zinc-900 p-4"
            aria-describedby="Drawer to Compose a new email"
          >
            <Drawer.Title className="text-xl">New Message</Drawer.Title>

            {error && (
              <Alert variant="destructive" className="bg-red-500/10">
                <AlertCircleIcon className="h-4 w-4" />
                <AlertTitle>There was an error.</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Input
              variant="underlined"
              startContent={
                <div className="flex w-[50px] justify-center text-sm text-foreground-500">
                  From
                </div>
              }
              disabled
              value={user.email}
              className="bg-zinc-800"
            />

            <div className="relative">
              <TagInput
                styleClasses={{
                  inlineTagsContainer:
                    "bg-zinc-800 border border-t-0 border-x-0 border-b-zinc-600! border-b-2 p-2 rounded-none",
                  tag: { body: "p-0 bg-white/20 pl-3 text-sm border-none" },
                }}
                shape="pill"
                animation="fadeIn"
                placeholder="To"
                tags={toEmails}
                setTags={setToEmails}
                activeTagIndex={activeTagIndex}
                setActiveTagIndex={setActiveTagIndex}
              />
              <Button
                isIconOnly
                className="absolute top-[3px] right-[3px]"
                size="sm"
                color="primary"
                onPress={() => setIsAiModalOpen(true)}
              >
                <AiSearch02Icon width={19} />
              </Button>
            </div>

            <Input
              placeholder="Subject"
              variant="underlined"
              className="bg-zinc-800"
              classNames={{ innerWrapper: "px-2" }}
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />

            <div className="relative flex h-full w-full flex-col">
              <div className="z-2 flex w-full justify-end gap-3 pb-2">
                {/* Writing Style Dropdown */}
                <div className="relative">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <ShadcnButton
                        className="border-none bg-[#00bbff40] text-sm font-normal text-[#00bbff] ring-0 outline-hidden hover:bg-[#00bbff20]"
                        size="sm"
                      >
                        <div className="flex flex-row gap-1">
                          <BrushIcon width={20} height={20} />
                          <span className="font-medium">
                            Writing Style:
                          </span>{" "}
                          <span>
                            {
                              writingStyles.find((s) => s.id === writingStyle)
                                ?.label
                            }
                          </span>
                          <ArrowDown01Icon width={20} />
                        </div>
                      </ShadcnButton>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="border-none bg-zinc-900 text-white dark">
                      {writingStyles.map((style) => (
                        <DropdownMenuItem
                          key={style.id}
                          onClick={() => {
                            setWritingStyle(style.id);
                            handleAskGaia(style.id);
                          }}
                          className="cursor-pointer focus:bg-zinc-600 focus:text-white"
                        >
                          <div className="flex w-full items-center justify-between">
                            {style.label}
                            {writingStyles.find((s) => s.id === writingStyle)
                              ?.label === style.label && (
                              <Tick02Icon width={20} height={20} />
                            )}
                          </div>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>

                {/* Content Length Dropdown */}
                <div className="relative">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <ShadcnButton
                        className="border-none bg-[#00bbff40] text-sm font-normal text-[#00bbff] ring-0 outline-hidden hover:bg-[#00bbff20]"
                        size="sm"
                      >
                        <div className="flex flex-row gap-1">
                          <BrushIcon width={20} height={20} />
                          <span className="font-medium">
                            Content Length:
                          </span>{" "}
                          <span>
                            {contentLengthOptions.find(
                              (opt) => opt.id === contentLength,
                            )?.label || "None"}
                          </span>
                          <ArrowDown01Icon width={20} />
                        </div>
                      </ShadcnButton>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="border-none bg-zinc-900 text-white dark">
                      {contentLengthOptions.map((option) => (
                        <DropdownMenuItem
                          key={option.id}
                          onClick={() => {
                            setContentLength(option.id);
                            handleAskGaia();
                          }}
                          className="cursor-pointer focus:bg-zinc-600 focus:text-white"
                        >
                          <div className="flex w-full items-center justify-between">
                            {option.label}
                            {contentLength === option.id && (
                              <Tick02Icon width={20} />
                            )}
                          </div>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>

                {/* Clarity Dropdown */}
                <div className="relative">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <ShadcnButton
                        className="border-none bg-[#00bbff40] text-sm font-normal text-[#00bbff] ring-0 outline-hidden hover:bg-[#00bbff20]"
                        size="sm"
                      >
                        <div className="flex flex-row gap-1">
                          <BrushIcon width={20} height={20} />
                          <span className="font-medium">Clarity:</span>{" "}
                          <span>
                            {clarityOptions.find(
                              (opt) => opt.id === clarityOption,
                            )?.label || "None"}
                          </span>
                          <ArrowDown01Icon width={20} />
                        </div>
                      </ShadcnButton>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="border-none bg-zinc-900 text-white dark">
                      {clarityOptions.map((option) => (
                        <DropdownMenuItem
                          key={option.id}
                          onClick={() => {
                            setClarityOption(option.id);
                            handleAskGaia();
                          }}
                          className="cursor-pointer focus:bg-zinc-600 focus:text-white"
                        >
                          <div className="flex w-full items-center justify-between">
                            {option.label}
                            {clarityOption === option.id && (
                              <Tick02Icon width={20} />
                            )}
                          </div>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>

              {editor && (
                <>
                  {/* <MenuBar editor={editor} textLength={false} isEmail={true} /> */}
                  <EditorContent className="bg-zinc-800 p-2" editor={editor} />
                </>
              )}
            </div>

            <footer className="flex w-full justify-end gap-5">
              <Input
                placeholder="What is the email about?"
                radius="full"
                classNames={{ inputWrapper: "pr-1 pl-0" }}
                className="pr-1"
                variant="faded"
                size="lg"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={handleAskGaiaKeyPress}
                startContent={
                  <Image
                    alt="GAIA Logo"
                    src={"/images/logos/logo.webp"}
                    width={25}
                    height={25}
                    className={`ml-2`}
                  />
                }
                endContent={
                  <Button
                    isIconOnly={loading}
                    color="primary"
                    radius="full"
                    onPress={() => handleAskGaia()}
                    isLoading={loading}
                  >
                    <div className="flex w-fit items-center gap-2 px-3 text-medium">
                      {!loading && (
                        <>
                          AI Draft
                          <SentIcon width={25} className="min-w-[25px]" />
                        </>
                      )}
                    </div>
                  </Button>
                }
              />

              <div className="flex items-center gap-2">
                <ButtonGroup color="primary">
                  <Button className="text-medium">
                    Send
                    <Sent02Icon width={23} height={23} />
                  </Button>
                </ButtonGroup>
              </div>
            </footer>
          </Drawer.Content>
        </Drawer.Portal>
      </Drawer.Root>
      <AiSearchModal
        open={isAiModalOpen}
        onOpenChange={setIsAiModalOpen}
        onSelect={handleAiSelect}
      />
    </>
  );
}
