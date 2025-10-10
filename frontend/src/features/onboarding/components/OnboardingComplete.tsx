import { motion } from "framer-motion";

import { RaisedButton } from "@/components/ui/shadcn/raised-button";

interface OnboardingCompleteProps {
  onLetsGo: () => void;
}

export const OnboardingComplete = ({ onLetsGo }: OnboardingCompleteProps) => {
  return (
    <motion.div
      className="mx-auto w-full max-w-2xl text-center"
      initial={{ opacity: 0, scale: 0.9, y: 15 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{
        duration: 0.5,
        ease: "easeOut",
        delay: 0.2,
      }}
    >
      <RaisedButton
        onClick={onLetsGo}
        color="#00bbff"
        className="mb-5 rounded-xl font-medium text-black! hover:scale-110"
      >
        Let's Go!
      </RaisedButton>
    </motion.div>
  );
};
