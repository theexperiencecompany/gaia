import { Accordion, AccordionItem } from "@heroui/accordion";
import type React from "react";
import { useState } from "react";

import CodeBlock from "@/features/chat/components/code-block/CodeBlock";
import type { CodeData } from "@/types/features/toolDataTypes";

import ChartDisplay from "./ChartDisplay";
import CodeExecutionOutput from "./CodeExecutionOutput";

interface CodeExecutionSectionProps {
  code_data: CodeData;
}

// Language display configuration
// const LANGUAGE_DISPLAY = {
//   python: { name: "Python", color: "text-blue-400" },
//   javascript: { name: "JavaScript", color: "text-yellow-400" },
//   typescript: { name: "TypeScript", color: "text-blue-500" },
//   ruby: { name: "Ruby", color: "text-red-400" },
//   php: { name: "PHP", color: "text-purple-400" },
// } as const;

// const getLanguageDisplay = (language: string) => {
//   const lang = language.toLowerCase() as keyof typeof LANGUAGE_DISPLAY;
//   return LANGUAGE_DISPLAY[lang] || { name: language, color: "text-gray-400" };
// };

const createCopyHandler = (
  text: string,
  setCopied: (value: boolean) => void,
) => {
  return () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
};

const CodeExecutionSection: React.FC<CodeExecutionSectionProps> = ({
  code_data,
}) => {
  const [outputCopied, setOutputCopied] = useState(false);

  const handleCopyOutput = createCopyHandler(
    [
      code_data.output?.stdout,
      code_data.output?.stderr,
      ...(code_data.output?.results || []),
    ]
      .filter(Boolean)
      .join("\n"),
    setOutputCopied,
  );

  return (
    <div className="w-full max-w-[30vw] rounded-3xl rounded-l-none bg-zinc-800 px-3 py-4">
      <Accordion
        selectionMode="multiple"
        defaultExpandedKeys={["output", "charts"]}
        className="w-full"
        variant="shadow"
      >
        <AccordionItem
          key="code"
          aria-label="Executed Code"
          title="Executed Code"
          classNames={{
            trigger: "text-sm font-medium text-gray-300 hover:text-white",
            content: "pt-0",
          }}
        >
          <div className="w-full max-w-[30vw] overflow-hidden rounded-[15px] rounded-b-[20px]">
            <CodeBlock className={`language-${code_data.language}`}>
              {code_data.code}
            </CodeBlock>
          </div>
        </AccordionItem>

        {/* Output Section */}
        <AccordionItem
          key="output"
          aria-label="Output"
          title="Output"
          classNames={{
            trigger: "text-sm font-medium text-gray-300 hover:text-white",
            content: "pt-0",
          }}
        >
          <CodeExecutionOutput
            output={code_data.output}
            status={code_data.status}
            language={code_data.language}
            onCopy={handleCopyOutput}
            copied={outputCopied}
          />
        </AccordionItem>

        {/* Charts Component */}
        {code_data.charts && code_data.charts.length > 0 ? (
          <AccordionItem
            key="charts"
            aria-label="Charts"
            title="Charts"
            classNames={{
              trigger: "text-sm font-medium text-gray-300 hover:text-white",
              content: "pt-0",
            }}
          >
            <ChartDisplay charts={code_data.charts} />
          </AccordionItem>
        ) : null}
      </Accordion>
    </div>
  );
};

export default CodeExecutionSection;
