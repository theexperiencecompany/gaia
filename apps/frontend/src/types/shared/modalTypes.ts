export interface BaseModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export interface BaseDialogProps {
  isOpen: boolean;
  onClose: () => void;
}
