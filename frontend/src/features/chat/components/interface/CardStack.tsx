"use client";

import { Button } from "@heroui/button";
import { motion } from "framer-motion";
import { ReactNode, useEffect, useRef, useState } from "react";

import { ArrowUpRight } from "@/icons";

interface CardStackProps<T> {
  title?: string;
  data: T[];
  indicator?: ReactNode;
  renderCard: (item: T) => ReactNode;
  viewAllHref?: string;
  className?: string;
  collapsedMessage?: (count: number) => string;
}

const defaultCollapsedMessage = (count: number) =>
  `You have ${count} unread item${count === 1 ? "" : "s"}`;

export default function CardStack<T extends { id: string }>({
  title = "Items",
  data,
  indicator = <div className="min-h-2 min-w-2 rounded-full bg-red-500" />,
  renderCard,
  viewAllHref,
  collapsedMessage = defaultCollapsedMessage,
  className = "mx-auto w-full max-w-3xs",
}: CardStackProps<T>) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [cardHeight, setCardHeight] = useState(62); // Default fallback
  const cardRef = useRef<HTMLDivElement>(null);

  const toggleExpanded = () => {
    setIsExpanded(!isExpanded);
  };

  // Measure the actual card height after first render
  useEffect(() => {
    if (cardRef.current) {
      const height = cardRef.current.offsetHeight;
      if (height > 0) {
        setCardHeight(height);
      }
    }
  }, [data.length, isExpanded]);

  return (
    <div className={className} onClick={toggleExpanded}>
      <motion.div
        initial={{ opacity: 0, y: -20, height: 0 }}
        animate={{
          opacity: isExpanded ? 1 : 0,
          y: isExpanded ? 0 : -20,
          height: isExpanded ? "auto" : 0,
        }}
        transition={{
          duration: 0.3,
          type: "spring",
          stiffness: 150,
          damping: 19,
          mass: 1.2,
        }}
        className="overflow-hidden"
      >
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: isExpanded ? 1 : 0 }}
          transition={{ duration: 0.2 }}
          className="mb-3 flex items-center justify-between text-white"
        >
          <h2 className="text-base font-medium select-none">{title}</h2>
          <Button
            onPress={toggleExpanded}
            variant="flat"
            color="primary"
            className="text-primary"
            radius="full"
            size="sm"
          >
            {isExpanded ? "Collapse" : "Expand"}
          </Button>
        </motion.div>
      </motion.div>

      <div
        className="relative"
        onClick={isExpanded ? undefined : toggleExpanded}
      >
        {data.map((item, index) => {
          // Calculate stacked positions for collapsed state
          const stackOffset = index * 8; // Vertical offset when stacked
          const stackScale = 1 - index * 0.1; // Progressive scaling when stacked
          const stackOpacity = 1 - index * 0.4; // Slight opacity reduction for depth

          return (
            <motion.div
              key={item.id}
              ref={index === 0 ? cardRef : undefined}
              initial={false}
              animate={{
                y: isExpanded ? index * cardHeight * 1.05 : -stackOffset,
                scale: isExpanded ? 0.98 : index === 0 ? 1.02 : stackScale,
                opacity: isExpanded ? 1 : stackOpacity,
                zIndex: data.length - index,
              }}
              transition={{
                y: {
                  type: "spring",
                  stiffness: 320,
                  damping: 20,
                  mass: 0.4,
                },
                scale: {
                  type: "spring",
                  stiffness: 400,
                  damping: 25,
                  mass: 0.5,
                },
                opacity: {
                  duration: 0.2,
                },
                delay: isExpanded
                  ? index * 0.1
                  : (data.length - index - 1) * 0.1,
              }}
              className={`group absolute top-0 right-0 left-0 flex min-h-10 w-full cursor-pointer items-center justify-center ${isExpanded ? "rounded-xl" : "rounded-xl"} rounded-2xl bg-zinc-700 p-3 transition-colors select-none`}
              style={{
                transformOrigin: "center top",
              }}
            >
              <div className="flex w-full items-start gap-1">
                {!isExpanded && index === 0 ? (
                  <div className="flex w-full items-center gap-2 px-4">
                    {indicator}
                    <p className="min-w-0 flex-1 overflow-hidden text-xs font-medium text-ellipsis whitespace-nowrap text-foreground-600">
                      {collapsedMessage(data.length)}
                    </p>
                  </div>
                ) : (
                  isExpanded && renderCard(item)
                )}
              </div>
            </motion.div>
          );
        })}
      </div>

      <motion.div
        initial={false}
        animate={{
          height: isExpanded ? data.length * cardHeight * 1.07 : 80,
          opacity: isExpanded ? 1 : 0,
        }}
        transition={{
          duration: 0.3,
          type: "spring",
          stiffness: 150,
          damping: 19,
          mass: 1.2,
        }}
        className="flex justify-center pt-4"
      />
      {isExpanded && viewAllHref && (
        <div className="flex w-full justify-center">
          <Button
            href={viewAllHref}
            variant="light"
            className="flex gap-1 text-foreground-400"
            size="sm"
            endContent={<ArrowUpRight width={14} className="outline-0!" />}
          >
            View All
          </Button>
        </div>
      )}
    </div>
  );
}
