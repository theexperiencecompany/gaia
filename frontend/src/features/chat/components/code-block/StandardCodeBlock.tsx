import { Button } from "@heroui/button";
import React from "react";
import { PrismAsyncLight } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";

import { Copy01Icon, Tick02Icon } from "@/icons";

import DownloadButton from "./DownloadButton";
import { getLanguageIcon } from "./languageIcons";

interface StandardCodeBlockProps {
  className?: string;
  children: React.ReactNode;
  copied: boolean;
  onCopy: () => void;
}

const StandardCodeBlock: React.FC<StandardCodeBlockProps> = ({
  className,
  children,
  copied,
  onCopy,
}) => {
  const match = /language-(\w+)/.exec(className || "");
  const language = match ? match[1] : undefined;
  const iconClass = getLanguageIcon(language);

  return (
    <div className="relative my-2 flex flex-col gap-0 rounded-xl">
      <div className="sticky! top-0 mb-[-0.5em] flex items-center justify-between rounded-t-xl! rounded-b-none! bg-zinc-900 px-4 py-1 text-white">
        <span className="monospace flex items-center gap-2 font-mono text-xs">
          <div className="text-base">
            {iconClass && <i className={`${iconClass} colored`} />}
          </div>
          {language || ""}
        </span>
        <div className="flex items-center gap-1">
          <DownloadButton
            content={String(children)}
            language={match ? match[1] : undefined}
          />
          <Button
            className="text-xs text-zinc-400 hover:text-gray-300"
            size="sm"
            isIconOnly
            variant="light"
            onPress={onCopy}
          >
            {copied ? (
              <Tick02Icon width={18} height={18} />
            ) : (
              <Copy01Icon width={18} height={18} />
            )}
          </Button>
        </div>
      </div>
      <PrismAsyncLight
        showLineNumbers
        className="overflow-x-auto rounded-b-xl"
        language={match ? match[1] : undefined}
        style={vscDarkPlus}
      >
        {String(children).replace(/\n$/, "")}
      </PrismAsyncLight>
    </div>
  );
};

export default StandardCodeBlock;
