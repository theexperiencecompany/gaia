/** Shared card shell: rounded, flat, no outline, no shadow — matches GAIA surfaces. */
export function LinkCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center p-4">
      <div className="w-full max-w-md rounded-3xl bg-zinc-900 p-8 text-center">
        {children}
      </div>
    </div>
  );
}
