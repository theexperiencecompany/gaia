"use client";

import { redirect } from "next/navigation";

interface WorkflowPageProps {
  params: {
    id: string;
  };
}

export default function WorkflowPage({ params }: WorkflowPageProps) {
  // Redirect to workflows page with the ID as a URL parameter
  // This allows the main WorkflowPage component to handle the modal opening
  redirect(`/workflows?id=${params.id}`);
}
