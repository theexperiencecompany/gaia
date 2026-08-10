"use client";

import { Priority } from "@shared/types";
import { addDays } from "date-fns";
import { useMemo } from "react";

import { getBrowserTimezone } from "@/lib/timezone";

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

// Project pattern: @projectName followed by space (complete patterns only)
function extractProject(
  cleanText: string,
  projects: Array<{ id: string; name: string }>,
  commands: TextProcessorCommands,
): string {
  const projectMatches = cleanText.match(/@([a-zA-Z0-9_-]+)\s/g);
  if (!projectMatches) return cleanText;

  let result = cleanText;
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
    result = result.replace(match, " ");
  });
  return result;
}

// Labels pattern: #labelName followed by space (complete patterns only)
function extractLabels(
  cleanText: string,
  commands: TextProcessorCommands,
): string {
  const labelMatches = cleanText.match(/#([a-zA-Z0-9_-]+)\s/g);
  if (!labelMatches) return cleanText;

  commands.labels = labelMatches.map((match) => match.slice(1, -1)); // Remove # and space
  let result = cleanText;
  labelMatches.forEach((match) => {
    // Replace only #labelName but keep the trailing space
    result = result.replace(match, " ");
  });
  return result;
}

// Priority patterns: p1/p2/p3, high/medium/low, urgent/important
function extractPriority(
  cleanText: string,
  commands: TextProcessorCommands,
): string {
  const numericMatch = cleanText.match(/\bp([123])\b/i);
  if (numericMatch) {
    const priorityNum = numericMatch[1];
    commands.priority =
      priorityNum === "1"
        ? Priority.HIGH
        : priorityNum === "2"
          ? Priority.MEDIUM
          : Priority.LOW;
    return cleanText.replace(numericMatch[0], " ");
  }

  // Check for word-based priorities
  const wordMatch = cleanText.match(
    /\b(high|urgent|important|medium|normal|low)\b/i,
  );
  if (wordMatch) {
    const priority = wordMatch[1].toLowerCase();
    commands.priority = ["high", "urgent", "important"].includes(priority)
      ? Priority.HIGH
      : ["medium", "normal"].includes(priority)
        ? Priority.MEDIUM
        : Priority.LOW;
    return cleanText.replace(wordMatch[0], " ");
  }

  return cleanText;
}

// Natural-language date patterns; last match wins for commands.dueDate.
function extractDueDate(
  cleanText: string,
  timezone: string,
  commands: TextProcessorCommands,
): string {
  let result = cleanText;

  const setDueDate = (date: Date, match: string) => {
    commands.dueDate = { date: date.toISOString(), timezone };
    result = result.replace(match, " ");
  };

  // Today, tomorrow, yesterday
  const todayMatch = result.match(/\btoday\b/i);
  if (todayMatch) setDueDate(new Date(), todayMatch[0]);

  const tomorrowMatch = result.match(/\btomorrow\b/i);
  if (tomorrowMatch) setDueDate(addDays(new Date(), 1), tomorrowMatch[0]);

  const yesterdayMatch = result.match(/\byesterday\b/i);
  if (yesterdayMatch) setDueDate(addDays(new Date(), -1), yesterdayMatch[0]);

  // "in X days" pattern
  const inDaysMatch = result.match(/\bin\s+(\d+)\s+days?\b/i);
  if (inDaysMatch) {
    const days = parseInt(inDaysMatch[1], 10);
    setDueDate(addDays(new Date(), days), inDaysMatch[0]);
  }

  // "next week" pattern
  const nextWeekMatch = result.match(/\bnext\s+week\b/i);
  if (nextWeekMatch) setDueDate(addDays(new Date(), 7), nextWeekMatch[0]);

  // "this weekend" pattern (Saturday)
  const weekendMatch = result.match(/\bthis\s+weekend\b/i);
  if (weekendMatch) {
    const today = new Date();
    const dayOfWeek = today.getDay(); // 0 = Sunday, 6 = Saturday
    const daysUntilSaturday = (6 - dayOfWeek + 7) % 7;
    setDueDate(addDays(today, daysUntilSaturday || 7), weekendMatch[0]);
  }

  // "next monday/tuesday/etc" pattern
  const nextDayMatch = result.match(
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
    setDueDate(addDays(today, daysUntilNextDay), nextDayMatch[0]);
  }

  return result;
}

export function useTextProcessor({
  projects,
  userTimezone,
}: UseTextProcessorProps) {
  const processText = useMemo(() => {
    return (text: string): ProcessedText => {
      if (!text) return { cleanText: "", commands: {} };

      const commands: TextProcessorCommands = {};
      const timezone = userTimezone || getBrowserTimezone();

      let cleanText = extractProject(text, projects, commands);
      cleanText = extractLabels(cleanText, commands);
      cleanText = extractPriority(cleanText, commands);
      cleanText = extractDueDate(cleanText, timezone, commands);

      // Clean up extra whitespace
      cleanText = cleanText.replace(/\s+/g, " ").trim();

      return { cleanText, commands };
    };
  }, [projects, userTimezone]);

  return { processText };
}
