import { Tab, Tabs } from "@heroui/tabs";
import dynamic from "next/dynamic";
import type React from "react";

// Dynamic imports for Mermaid-related components
const FlowchartPreview = dynamic(() => import("./FlowchartPreview"), {
  ssr: false,
  loading: () => (
    <div className="flex h-40 items-center justify-center text-sm text-gray-500">
      Loading preview...
    </div>
  ),
});

const MermaidCode = dynamic(() => import("./MermaidCode"), {
  ssr: false,
  loading: () => (
    <div className="flex h-20 items-center justify-center text-sm text-gray-500">
      Loading code...
    </div>
  ),
});

interface SyntaxHighlighterProps {
  language?: string;
  style?: { [key: string]: unknown };
  customStyle?: { [key: string]: unknown };
  className?: string;
  showLineNumbers?: boolean;
  startingLineNumber?: number;
  wrapLines?: boolean;
  lineProps?: { [key: string]: unknown };
}

interface MermaidTabsProps {
  children: React.ReactNode;
  activeTab: string;
  onTabChange: (key: string) => void;
  isLoading: boolean;
  syntaxHighlighterProps?: SyntaxHighlighterProps;
}

const MermaidTabs: React.FC<MermaidTabsProps> = ({
  children,
  activeTab,
  onTabChange,
  isLoading,
  syntaxHighlighterProps,
}) => {
  return (
    <Tabs
      className="px-3"
      disabledKeys={isLoading ? ["editor"] : []}
      selectedKey={activeTab}
      variant="underlined"
      onSelectionChange={(key) => onTabChange(key as string)}
    >
      <Tab key="preview" className="p-0" title="Flowchart">
        <FlowchartPreview>{children}</FlowchartPreview>
      </Tab>
      <Tab key="code" title="Code">
        <MermaidCode syntaxHighlighterProps={syntaxHighlighterProps}>
          {children}
        </MermaidCode>
      </Tab>
    </Tabs>
  );
};

export default MermaidTabs;
