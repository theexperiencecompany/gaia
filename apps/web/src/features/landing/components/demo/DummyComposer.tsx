import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { Kbd } from "@heroui/kbd";
import { Tooltip } from "@heroui/tooltip";
import {
  ArrowRight01Icon,
  ArrowUp02Icon,
  AttachmentIcon,
  PlusSignIcon,
  ToolsIcon,
} from "@icons";
import { twMerge } from "cn";
import type React from "react";
import { useRef, useState } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { dummyIntegrations } from "./constants";
import DummySlashCommandDropdown from "./DummySlashCommandDropdown";

const DummyComposer: React.FC<{
  hideIntegrationBanner?: boolean;
  fullWidth?: boolean;
  onSend?: (message: string) => void;
  className?: string;
}> = ({
  hideIntegrationBanner = false,
  fullWidth = false,
  onSend,
  className,
}) => {
  const [message, setMessage] = useState("");
  const [isSlashDropdownOpen, setIsSlashDropdownOpen] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);

  const handleInputChange = (value: string) => {
    setMessage(value);
    if (value.startsWith("/")) {
      setIsSlashDropdownOpen(true);
    } else if (isSlashDropdownOpen && !value.startsWith("/")) {
      setIsSlashDropdownOpen(false);
    }
  };

  const handleSlashButtonClick = () => {
    setIsSlashDropdownOpen((prev) => !prev);
  };

  const handleIntegrationsClick = () => {
    setIsSlashDropdownOpen((prev) => !prev);
  };

  const handleSend = () => {
    if (message.trim()) {
      onSend?.(message);
      setMessage("");
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      // Don't commit while an IME composition is in flight — Enter confirms
      // the CJK candidate there, it doesn't send the message.
      if (e.nativeEvent.isComposing) return;
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div
      className={twMerge(
        "mx-auto flex w-full max-w-7xl flex-col items-center",
        className,
      )}
    >
      {/* Composer */}
      <div className="searchbar_container relative w-full pb-1">
        {/* Slash dropdown — absolute, overlays upward into messages area */}
        <div className="searchbar absolute bottom-full z-200 -mb-3 w-full max-w-lg">
          <DummySlashCommandDropdown
            isVisible={isSlashDropdownOpen}
            onClose={() => setIsSlashDropdownOpen(false)}
            openedViaButton={true}
          />
        </div>
        {/* Integration Banner - uses searchbar class to match composer width */}
        {!hideIntegrationBanner && (
          <Button
            variant="flat"
            radius="full"
            onPress={handleIntegrationsClick}
            aria-label="Connect your tools to GAIA"
            className="absolute -top-4 z-0 flex h-fit text-xs text-foreground-300 hover:text-zinc-400"
          >
            <div className="flex w-full items-center justify-between">
              <span className="text-xs">Connect your tools to GAIA</span>
              <div className="flex items-center gap-1">
                {dummyIntegrations.slice(0, 7).map((integration) => (
                  <div
                    key={integration.id}
                    className="opacity-60 transition duration-200 hover:scale-150 hover:rotate-6 hover:opacity-120"
                    title={integration.name}
                  >
                    {getToolCategoryIcon(integration.id, {
                      size: 14,
                      width: 14,
                      height: 14,
                      showBackground: false,
                      className: "h-[14px] w-[14px] object-contain",
                    })}
                  </div>
                ))}
                <ArrowRight01Icon width={18} height={18} className="ml-3" />
              </div>
            </div>
          </Button>
        )}

        {/* Main Composer */}
        <div
          ref={composerRef}
          className={`relative z-2 rounded-3xl bg-zinc-800 px-1 pt-1 pb-2 ${fullWidth ? "w-full" : "searchbar"}`}
        >
          {/* Textarea Input */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            aria-label="Demo chat input - not a real form submission"
            data-demo="true"
          >
            <Textarea
              ref={textareaRef}
              autoFocus
              classNames={{
                innerWrapper: "items-center",
                input: "font-light",
              }}
              maxRows={13}
              minRows={1}
              placeholder="What can I do for you today?"
              size="lg"
              value={message}
              onValueChange={handleInputChange}
              onKeyDown={handleKeyPress}
              endContent={
                <div className="flex items-center gap-1 text-xs text-nowrap text-foreground-500">
                  <Kbd>/</Kbd>
                  for tools
                </div>
              }
            />
          </form>

          {/* Toolbar */}
          <div className="flex items-center justify-between px-2 pt-1">
            <div className="flex items-center justify-start gap-2">
              {/* Add Context Dropdown */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    isIconOnly
                    radius="full"
                    variant="flat"
                    className="group relative h-9 w-9"
                    aria-label="Add context or attach files"
                  >
                    <PlusSignIcon className="min-h-[23px] min-w-[23px] text-zinc-400!" />
                    <span
                      className="absolute -top-0 -right-0 h-2 w-2 rounded-full bg-primary opacity-0 transition"
                      aria-hidden="true"
                    />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" side="top" className="w-fit">
                  <Tooltip
                    content={
                      <div className="max-w-[270px]">
                        Upload and analyze documents, images or other files
                      </div>
                    }
                    color="foreground"
                    radius="sm"
                  >
                    <DropdownMenuItem className="cursor-pointer">
                      <div className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2">
                        <div className="flex flex-col">
                          <div className="flex flex-row items-center gap-2">
                            <AttachmentIcon className="min-h-[20px] min-w-[20px] text-primary" />
                            <span>Attach Files</span>
                          </div>
                        </div>
                      </div>
                    </DropdownMenuItem>
                  </Tooltip>
                </DropdownMenuContent>
              </DropdownMenu>

              {/* Tools Button */}
              <Tooltip
                content="Browse all tools"
                placement="right"
                color="primary"
                showArrow
              >
                <Button
                  isIconOnly
                  radius="full"
                  variant="flat"
                  color={isSlashDropdownOpen ? "primary" : "default"}
                  className={`group relative h-9 w-9`}
                  onClick={handleSlashButtonClick}
                  aria-label="Browse all tools"
                >
                  <ToolsIcon
                    className="min-h-[23px] min-w-[23px]"
                    width={30}
                    height={30}
                  />
                  {isSlashDropdownOpen && (
                    <span
                      className="absolute top-0 right-0 h-2 w-2 rounded-full bg-primary transition"
                      aria-hidden="true"
                    />
                  )}
                </Button>
              </Tooltip>
            </div>

            {/* Send Button */}
            <Button
              type="submit"
              isIconOnly
              radius="full"
              color="primary"
              onClick={handleSend}
              isDisabled={!message.trim()}
              className="h-9 w-9 text-xl"
              aria-label="Send message"
            >
              <ArrowUp02Icon
                width={40}
                height={40}
                className="min-h-5 min-w-5"
              />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DummyComposer;
