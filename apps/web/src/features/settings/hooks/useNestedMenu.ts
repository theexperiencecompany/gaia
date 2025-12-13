import { useState } from "react";

export function useNestedMenu() {
  const [isOpen, setIsOpen] = useState(false);
  const [itemRef, setItemRef] = useState<HTMLElement | null>(null);

  const handleMouseEnter = (e: React.MouseEvent<HTMLElement>) => {
    setItemRef(e.currentTarget as HTMLElement);
    setIsOpen(true);
  };

  const handleMouseLeave = () => {
    setIsOpen(false);
  };

  return {
    isOpen,
    setIsOpen,
    itemRef,
    handleMouseEnter,
    handleMouseLeave,
  };
}
