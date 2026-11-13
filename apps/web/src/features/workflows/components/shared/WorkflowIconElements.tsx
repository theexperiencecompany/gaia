"use client";

import { createContext, type ReactNode, useContext } from "react";
import { workflowIconKey } from "../../constants/workflowIconStyle";

/**
 * Catalog icons a server parent rendered at one size, keyed by workflowIconKey,
 * so cards draw them without the client catalog. They arrive as RSC output, so
 * they are placed as-is, never cloned (a Flight node is not always an element).
 */
export interface WorkflowIconElements {
  readonly size: number;
  readonly elements: Readonly<Record<string, ReactNode>>;
}

const WorkflowIconElementsContext = createContext<WorkflowIconElements | null>(
  null,
);

export function WorkflowIconElementsProvider({
  icons,
  children,
}: {
  icons: WorkflowIconElements;
  children: ReactNode;
}) {
  return (
    <WorkflowIconElementsContext.Provider value={icons}>
      {children}
    </WorkflowIconElementsContext.Provider>
  );
}

/** The server-rendered icon for this slug, color and size, if a parent supplied one. */
export function useWorkflowIconElement(
  icon: string | null | undefined,
  iconColor: string | null | undefined,
  size: number,
): ReactNode | undefined {
  const icons = useContext(WorkflowIconElementsContext);
  if (!icon || icons?.size !== size) return undefined;
  return icons.elements[workflowIconKey(icon, iconColor)];
}
