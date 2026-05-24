import { Text } from "@/components/ui/text";

interface SectionLabelProps {
  children: string;
}

export function SectionLabel({ children }: SectionLabelProps) {
  return (
    <Text className="text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-1.5">
      {children}
    </Text>
  );
}
