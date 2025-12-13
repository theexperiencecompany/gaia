interface StatusIndicatorProps {
  isUpdating: boolean;
  hasUnsavedChanges: boolean;
  className?: string;
}

export function StatusIndicator({
  isUpdating,
  hasUnsavedChanges,
  className = "",
}: StatusIndicatorProps) {
  const getStatusMessage = () => {
    if (isUpdating) return "Saving preferences...";
    if (hasUnsavedChanges && !isUpdating) return "Unsaved changes";
    return "All changes saved";
  };

  return (
    <div className={`text-center ${className}`}>
      <p className="text-xs text-zinc-500">{getStatusMessage()}</p>
    </div>
  );
}
