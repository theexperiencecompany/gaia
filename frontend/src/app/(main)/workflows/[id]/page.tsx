"use client";

import { redirect } from "next/navigation";

interface WorkflowPageProps {
  params: {
    id: string;
  };
}

/**
 * User workflow detail page - redirects to workflows page with modal
 * Note: Community workflows should navigate to /use-cases/[slug] instead
 */
export default function WorkflowPage({ params }: WorkflowPageProps) {
  // Redirect to workflows page with the ID as a URL parameter
  // This allows the main WorkflowPage component to handle the modal opening
  redirect(`/workflows?id=${params.id}`);
}
