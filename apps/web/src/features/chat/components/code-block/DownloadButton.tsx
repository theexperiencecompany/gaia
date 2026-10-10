import { Button } from "@heroui/button";
import { Download01Icon } from "@icons";
import type React from "react";

interface DownloadButtonProps {
  content: string;
  language?: string;
}

const EXTENSION_BY_LANGUAGE: Record<string, string> = {
  javascript: "js",
  typescript: "ts",
  python: "py",
  java: "java",
  cpp: "cpp",
  c: "c",
  csharp: "cs",
  php: "php",
  ruby: "rb",
  go: "go",
  rust: "rs",
  swift: "swift",
  kotlin: "kt",
  scala: "scala",
  html: "html",
  css: "css",
  scss: "scss",
  sass: "sass",
  json: "json",
  xml: "xml",
  yaml: "yaml",
  yml: "yml",
  markdown: "md",
  sql: "sql",
  shell: "sh",
  bash: "sh",
  zsh: "sh",
  powershell: "ps1",
  dockerfile: "dockerfile",
  jsx: "jsx",
  tsx: "tsx",
  vue: "vue",
  svelte: "svelte",
  mermaid: "mmd",
};

const getFileExtension = (lang?: string): string =>
  EXTENSION_BY_LANGUAGE[lang?.toLowerCase() || ""] || "txt";

const DownloadButton: React.FC<DownloadButtonProps> = ({
  content,
  language,
}) => {
  const handleDownload = () => {
    const extension = getFileExtension(language);
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `code.${extension}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <Button
      className="text-xs text-zinc-400 hover:text-gray-300"
      size="sm"
      isIconOnly
      variant="light"
      onPress={handleDownload}
    >
      <Download01Icon width={18} height={18} />
    </Button>
  );
};

export default DownloadButton;
