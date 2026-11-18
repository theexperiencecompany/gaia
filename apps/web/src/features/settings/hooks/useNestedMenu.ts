import { useCallback, useEffect, useRef, useState } from "react";

// Long enough to cross the gap between a menu item and its flyout, short
// enough that the flyout still feels tied to the item.
const CLOSE_DELAY_MS = 120;

export function useNestedMenu() {
  const [isOpen, setIsOpenState] = useState(false);
  const [itemRef, setItemRef] = useState<HTMLElement | null>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelClose = useCallback(() => {
    if (closeTimerRef.current !== null) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const setIsOpen = useCallback(
    (open: boolean) => {
      cancelClose();
      setIsOpenState(open);
    },
    [cancelClose],
  );

  const handleMouseEnter = (e: React.MouseEvent<HTMLElement>) => {
    setItemRef(e.currentTarget as HTMLElement);
    setIsOpen(true);
  };

  const handleMouseLeave = () => {
    cancelClose();
    closeTimerRef.current = setTimeout(() => {
      closeTimerRef.current = null;
      setIsOpenState(false);
    }, CLOSE_DELAY_MS);
  };

  useEffect(() => cancelClose, [cancelClose]);

  return {
    isOpen,
    setIsOpen,
    itemRef,
    handleMouseEnter,
    handleMouseLeave,
  };
}
