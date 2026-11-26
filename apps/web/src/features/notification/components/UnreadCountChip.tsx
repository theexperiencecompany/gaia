interface UnreadCountChipProps {
  count: number;
}

export const UnreadCountChip = ({ count }: UnreadCountChipProps) => {
  if (count === 0) return null;

  return (
    <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-current/15 px-1.5 text-xs font-medium tabular-nums">
      {count > 99 ? "99+" : count}
    </span>
  );
};
