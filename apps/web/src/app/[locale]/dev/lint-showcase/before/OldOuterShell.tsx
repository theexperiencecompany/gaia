interface OldOuterShellProps {
  label: string;
}

// Old-rule outer shell (rounded-2xl) for the radius showdown. Placeholder
// content only — not a copy of any component.
export default function OldOuterShell({ label }: OldOuterShellProps) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <p className="text-sm font-medium text-zinc-200">{label}</p>
      <p className="mt-1 text-xs text-zinc-500">Old rule: rounded-2xl outer</p>
    </div>
  );
}
