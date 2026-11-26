interface UnreadCountChipProps {
  count: number;
}

export const UnreadCountChip = ({ count }: UnreadCountChipProps) => {
  if (count === 0) return null;

  return (
    <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-accent/10 px-1.5 text-xs font-medium text-accent tabular-nums">
      {count > 99 ? "99+" : count}
    </span>
  );
};
