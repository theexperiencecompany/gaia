interface UnreadCountChipProps {
  count: number;
}

export const UnreadCountChip = ({ count }: UnreadCountChipProps) => {
  if (count === 0) return null;

  return (
    <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary/10 px-1.5 text-xs font-semibold text-primary">
      {count > 99 ? "99+" : count}
    </span>
  );
};
