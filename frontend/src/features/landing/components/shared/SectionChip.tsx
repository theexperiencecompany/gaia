import { LucideIcon } from "lucide-react";
import React from "react";

interface SectionChipProps {
  text: string;
  icon?: LucideIcon; // Optional Lucide icon
}

const SectionChip: React.FC<SectionChipProps> = ({ text, icon: Icon }) => {
  return (
    <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/5 px-4 py-2 backdrop-blur-sm">
      {Icon && <Icon className="h-4 w-4 text-[#01BBFF]" />}
      <span className="text-sm font-medium text-white/90">{text}</span>
    </div>
  );
};

export default SectionChip;
