"use client";

import { addDays } from "date-fns";
import { useMemo } from "react";

import { Priority } from "@/types/features/todoTypes";

export interface TextProcessorCommands {
  project?: { name: string; id?: string };
  labels?: string[];
  priority?: Priority;
  dueDate?: { date: string; timezone?: string };
}

export interface ProcessedText {
  cleanText: string;
  commands: TextProcessorCommands;
}

interface UseTextProcessorProps {
  projects: Array<{ id: string; name: string }>;
  userTimezone?: string;
}

export function useTextProcessor({
  projects,
  userTimezone,
}: UseTextProcessorProps) {
  const processText = useMemo(() => {
    return (text: string): ProcessedText => {
      if (!text) return { cleanText: "", commands: {} };

      let cleanText = text;
      const commands: TextProcessorCommands = {};

      // Project pattern: @projectName followed by space (complete patterns only)
      const projectMatches = cleanText.match(/@([a-zA-Z0-9_-]+)\s/g);
      if (projectMatches) {
        projectMatches.forEach((match) => {
          const projectName = match.slice(1, -1).toLowerCase(); // Remove @ and trailing space
          const project = projects.find(
            (p) =>
              p.name.toLowerCase() === projectName ||
              p.name.toLowerCase().includes(projectName) ||
              projectName.includes(p.name.toLowerCase()),
          );

          if (project) {
            commands.project = { name: project.name, id: project.id };
          } else {
            commands.project = { name: match.slice(1, -1) }; // Remove @ and space
          }
          // Replace only @projectName but keep the trailing space
          cleanText = cleanText.replace(match, " ");
        });
      }

      // Labels pattern: #labelName followed by space (complete patterns only)
      const labelMatches = cleanText.match(/#([a-zA-Z0-9_-]+)\s/g);
      if (labelMatches) {
        commands.labels = labelMatches.map((match) => match.slice(1, -1)); // Remove # and space
        labelMatches.forEach((match) => {
          // Replace only #labelName but keep the trailing space
          cleanText = cleanText.replace(match, " ");
        });
      }

      // Priority patterns: p1/p2/p3, high/medium/low, urgent/important
      let priorityMatch = cleanText.match(/\bp([123])\b/i);
      if (priorityMatch) {
        const priorityNum = priorityMatch[1];
        commands.priority =
          priorityNum === "1"
            ? Priority.HIGH
            : priorityNum === "2"
              ? Priority.MEDIUM
              : Priority.LOW;
        cleanText = cleanText.replace(priorityMatch[0], " ");
      } else {
        // Check for word-based priorities
        priorityMatch = cleanText.match(
          /\b(high|urgent|important|medium|normal|low)\b/i,
        );
        if (priorityMatch) {
          const priority = priorityMatch[1].toLowerCase();
          commands.priority = ["high", "urgent", "important"].includes(priority)
            ? Priority.HIGH
            : ["medium", "normal"].includes(priority)
              ? Priority.MEDIUM
              : Priority.LOW;
          cleanText = cleanText.replace(priorityMatch[0], " ");
        }
      }

      // Date patterns
      const timezone =
        userTimezone || Intl.DateTimeFormat().resolvedOptions().timeZone;

      // Today, tomorrow, yesterday
      const todayMatch = cleanText.match(/\btoday\b/i);
      if (todayMatch) {
        commands.dueDate = {
          date: new Date().toISOString(),
          timezone,
        };
        cleanText = cleanText.replace(todayMatch[0], " ");
      }

      const tomorrowMatch = cleanText.match(/\btomorrow\b/i);
      if (tomorrowMatch) {
        commands.dueDate = {
          date: addDays(new Date(), 1).toISOString(),
          timezone,
        };
        cleanText = cleanText.replace(tomorrowMatch[0], " ");
      }

      const yesterdayMatch = cleanText.match(/\byesterday\b/i);
      if (yesterdayMatch) {
        commands.dueDate = {
          date: addDays(new Date(), -1).toISOString(),
          timezone,
        };
        cleanText = cleanText.replace(yesterdayMatch[0], " ");
      }

      // "in X days" pattern
      const inDaysMatch = cleanText.match(/\bin\s+(\d+)\s+days?\b/i);
      if (inDaysMatch) {
        const days = parseInt(inDaysMatch[1], 10);
        commands.dueDate = {
          date: addDays(new Date(), days).toISOString(),
          timezone,
        };
        cleanText = cleanText.replace(inDaysMatch[0], " ");
      }

      // "next week" pattern
      const nextWeekMatch = cleanText.match(/\bnext\s+week\b/i);
      if (nextWeekMatch) {
        commands.dueDate = {
          date: addDays(new Date(), 7).toISOString(),
          timezone,
        };
        cleanText = cleanText.replace(nextWeekMatch[0], " ");
      }

      // "this weekend" pattern (Saturday)
      const weekendMatch = cleanText.match(/\bthis\s+weekend\b/i);
      if (weekendMatch) {
        const today = new Date();
        const dayOfWeek = today.getDay(); // 0 = Sunday, 6 = Saturday
        const daysUntilSaturday = (6 - dayOfWeek + 7) % 7;
        commands.dueDate = {
          date: addDays(today, daysUntilSaturday || 7).toISOString(),
          timezone,
        };
        cleanText = cleanText.replace(weekendMatch[0], " ");
      }

      // "next monday/tuesday/etc" pattern
      const nextDayMatch = cleanText.match(
        /\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i,
      );
      if (nextDayMatch) {
        const dayName = nextDayMatch[1].toLowerCase();
        const dayIndex = [
          "sunday",
          "monday",
          "tuesday",
          "wednesday",
          "thursday",
          "friday",
          "saturday",
        ].indexOf(dayName);
        const today = new Date();
        const todayIndex = today.getDay();
        const daysUntilNextDay = (dayIndex - todayIndex + 7) % 7 || 7;

        commands.dueDate = {
          date: addDays(today, daysUntilNextDay).toISOString(),
          timezone,
        };
        cleanText = cleanText.replace(nextDayMatch[0], " ");
      }

      // Clean up extra whitespace
      cleanText = cleanText.replace(/\s+/g, " ").trim();

      return { cleanText, commands };
    };
  }, [projects, userTimezone]);

  return { processText };
}
