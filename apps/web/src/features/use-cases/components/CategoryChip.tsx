import { Chip } from "@heroui/chip";
import { StarAward01Icon, WorkflowCircle03Icon } from "@icons";
import * as m from "motion/react-m";

interface CategoryChipProps {
  category: string;
  index: number;
  isSelected: boolean;
  onClick: () => void;
}

export function CategoryChip({
  category,
  index,
  isSelected,
  onClick,
}: CategoryChipProps) {
  return (
    <m.div
      className="shrink-0"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.3,
        delay: index * 0.05,
        ease: "easeOut",
      }}
    >
      <Chip
        variant={isSelected ? "solid" : "flat"}
        color={isSelected ? "primary" : "default"}
        className={`cursor-pointer capitalize ${isSelected ? "" : "bg-white/5! text-foreground-500"} font-light! backdrop-blur-2xl!`}
        size="lg"
        startContent={
          category === "featured" ? (
            <StarAward01Icon width={18} height={18} />
          ) : category === "workflows" ? (
            <WorkflowCircle03Icon width={18} height={18} />
          ) : undefined
        }
        onClick={onClick}
      >
        {category === "all"
          ? "All"
          : category === "featured"
            ? "Featured"
            : category === "workflows"
              ? "Your Workflows"
              : category}
      </Chip>
    </m.div>
  );
}
