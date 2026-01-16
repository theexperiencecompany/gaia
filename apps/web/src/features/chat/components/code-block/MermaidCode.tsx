import dynamic from "next/dynamic";
import type { CSSProperties } from "react";
import React from "react";

// Dynamic import for syntax highlighter - only load specific language
const PrismAsyncLight = dynamic(
  () => import("react-syntax-highlighter").then((mod) => mod.PrismAsyncLight),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-20 items-center justify-center text-sm text-foreground-500">
        Loading syntax highlighter...
      </div>
    ),
  },
);

// Dynamic import for the theme - split separately
const loadVscDarkPlusTheme = async () => {
  return await import(
    "react-syntax-highlighter/dist/esm/styles/prism/vsc-dark-plus"
  );
};

interface SyntaxHighlighterProps {
  style?: CSSProperties;
  language?: string;
  children?: React.ReactNode;
  className?: string;
  showLineNumbers?: boolean;
  lineNumberStyle?: CSSProperties;
  wrapLines?: boolean;
  wrapLongLines?: boolean;
  lineProps?: object | ((lineNumber: number) => object);
  customStyle?: CSSProperties;
  codeTagProps?: object;
  useInlineStyles?: boolean;
}

interface MermaidCodeProps {
  children: React.ReactNode;
  syntaxHighlighterProps?: SyntaxHighlighterProps;
}

const MermaidCode: React.FC<MermaidCodeProps> = ({
  children,
  syntaxHighlighterProps,
}) => {
  const [theme, setTheme] = React.useState<{
    [key: string]: CSSProperties;
  } | null>(null);

  React.useEffect(() => {
    loadVscDarkPlusTheme().then(setTheme);
  }, []);

  if (!theme) {
    return (
      <div className="flex h-20 items-center justify-center text-sm text-foreground-500">
        Loading theme...
      </div>
    );
  }

  return (
    <PrismAsyncLight
      {...syntaxHighlighterProps}
      showLineNumbers
      PreTag="div"
      className="m-0 overflow-x-auto rounded-b-xl bg-surface-100! p-0 text-[10px]!"
      language="mermaid"
      style={theme}
      customStyle={{} as CSSProperties}
    >
      {String(children).replace(/\n$/, "")}
    </PrismAsyncLight>
  );
};

export default MermaidCode;
