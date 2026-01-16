import { Button } from "@heroui/button";
import { motion } from "framer-motion";

import { useAppendToInput } from "@/stores/composerStore";

interface FollowUpActionsProps {
  actions: string[];
  loading: boolean;
}

export default function FollowUpActions({
  actions,
  loading,
}: FollowUpActionsProps) {
  const appendToInput = useAppendToInput();
  const handleActionClick = async (action: string) => {
    if (loading) return;

    try {
      appendToInput(action);
    } catch (error) {
      console.error("Failed to handle follow-up action:", error);
    }
  };

  if (!actions || actions.length === 0) return null;

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={{
        visible: {
          transition: {
            staggerChildren: 0.05,
          },
        },
      }}
      className="flex max-w-xl flex-wrap gap-2 pt-3 pb-1"
    >
      {actions.map((action) => (
        <motion.div
          key={action}
          variants={{
            hidden: { opacity: 0, y: 10 },
            visible: { opacity: 1, y: 0 },
          }}
        >
          <Button
            className="text-xs text-foreground-500 outline-1 outline-surface-300 transition-colors outline-dashed hover:bg-surface-300 hover:text-foreground-700"
            variant="light"
            size="sm"
            onPress={() => handleActionClick(action)}
            isDisabled={loading}
          >
            {action}
          </Button>
        </motion.div>
      ))}
    </motion.div>
  );
}
