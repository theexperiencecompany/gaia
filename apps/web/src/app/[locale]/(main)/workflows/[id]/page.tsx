import "./page.css";
import "./page.2.css";
import "./page.3.css";
import "./page.4.css";
import "./page.5.css";
import { permanentRedirect } from "next/navigation";

interface WorkflowPageProps {
  params: Promise<{ id: string }>;
}

/**
 * User workflow detail page - redirects to workflows page with modal.
 * Note: Community workflows should navigate to /use-cases/[slug] instead.
 */
export default async function WorkflowPage({ params }: WorkflowPageProps) {
  const { id } = await params;
  permanentRedirect(`/workflows?id=${id}`);
}
