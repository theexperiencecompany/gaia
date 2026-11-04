import { Tabs } from "@heroui/react";
import dynamic from "next/dynamic";
import type React from "react";
import type { CSSProperties } from "react";

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
  style?: CSSProperties;
  customStyle?: CSSProperties;
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
      onSelectionChange={(key) => onTabChange(String(key))}
    >
      <Tabs.List aria-label="Diagram">
        <Tabs.Tab id="preview" className="font-sans">
          Flowchart
          <Tabs.Indicator />
        </Tabs.Tab>
        <Tabs.Tab id="code" className="font-sans">
          Code
          <Tabs.Indicator />
        </Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel id="preview" className="p-0">
        <FlowchartPreview>{children}</FlowchartPreview>
      </Tabs.Panel>
      <Tabs.Panel id="code">
        <MermaidCode syntaxHighlighterProps={syntaxHighlighterProps}>
          {children}
        </MermaidCode>
      </Tabs.Panel>
    </Tabs>
  );
};

export default MermaidTabs;
