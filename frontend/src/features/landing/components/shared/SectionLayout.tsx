import type React from "react";

interface SectionLayoutProps {
  children: React.ReactNode;
  className?: string;
}

export default function SectionLayout({
  children,
  className = "",
}: SectionLayoutProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-10 p-10 ${className}`}
    >
      {children}
    </div>
  );
}
