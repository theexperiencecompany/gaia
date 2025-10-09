"use client";

import { Button } from "@heroui/button";
import { useDisclosure } from "@heroui/modal";
import { ExternalLink, RefreshCw, ZapIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import UseCaseSection from "@/features/use-cases/components/UseCaseSection";

import Link from "next/link";
import { toast } from "sonner";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { Workflow, CommunityWorkflow, workflowApi } from "../api/workflowApi";
import { useWorkflows } from "../hooks";
import { useWorkflowCreation } from "../hooks/useWorkflowCreation";
import CreateWorkflowModal from "./CreateWorkflowModal";
import EditWorkflowModal from "./EditWorkflowModal";
import WorkflowCard from "./WorkflowCard";
import CommunityWorkflowCard from "./CommunityWorkflowCard";
import { WorkflowListSkeleton } from "./WorkflowSkeletons";

export default function WorkflowPage() {
  const pageRef = useRef(null);
  const router = useRouter();
  const searchParams = useSearchParams();
  const workflowId = searchParams.get("id");

  const { isOpen, onOpen, onOpenChange } = useDisclosure();
  const {
    isOpen: isEditOpen,
    onOpen: onEditOpen,
    onOpenChange: onEditOpenChange,
  } = useDisclosure();

  const [selectedWorkflow, setSelectedWorkflow] = useState<Workflow | null>(
    null,
  );

  const { workflows, isLoading, error, refetch } = useWorkflows();
  const { createWorkflow } = useWorkflowCreation();
  const { selectWorkflow } = useWorkflowSelection();
  const [communityWorkflows, setCommunityWorkflows] = useState<
    CommunityWorkflow[]
  >([]);
  const [isLoadingCommunity, setIsLoadingCommunity] = useState(false);
  const [communityError, setCommunityError] = useState<string | null>(null);

  // Load community workflows
  useEffect(() => {
    const loadCommunityWorkflows = async () => {
      setIsLoadingCommunity(true);
      setCommunityError(null);
      try {
        const response = await workflowApi.getCommunityWorkflows(12, 0);
        setCommunityWorkflows(response.workflows);
      } catch (error) {
        console.error("Error loading community workflows:", error);
        setCommunityError(
          error instanceof Error
            ? error.message
            : "Failed to load community workflows",
        );
      } finally {
        setIsLoadingCommunity(false);
      }
    };

    loadCommunityWorkflows();
  }, []);

  // Handle URL-based modal opening
  useEffect(() => {
    if (workflowId && workflows.length > 0) {
      const workflow = workflows.find((w) => w.id === workflowId);
      if (workflow) {
        setSelectedWorkflow(workflow);
        onEditOpen();
      }
    }
  }, [workflowId, workflows, onEditOpen]);

  // Handle workflow creation completion
  const handleWorkflowCreated = useCallback(() => {
    refetch(); // Refresh the list to show the new workflow
  }, [refetch]);

  const handleWorkflowDeleted = useCallback(
    (workflowId: string) => {
      // TODO: Call delete API
      console.log("Workflow deleted:", workflowId);
      refetch(); // Refresh the list
    },
    [refetch],
  );

  const refetchCommunity = useCallback(async () => {
    setIsLoadingCommunity(true);
    setCommunityError(null);
    try {
      const response = await workflowApi.getCommunityWorkflows(12, 0);
      setCommunityWorkflows(response.workflows);
    } catch (error) {
      console.error("Error loading community workflows:", error);
      setCommunityError(
        error instanceof Error
          ? error.message
          : "Failed to load community workflows",
      );
    } finally {
      setIsLoadingCommunity(false);
    }
  }, []);

  const handleWorkflowClick = (workflowId: string) => {
    const workflow = workflows.find((w) => w.id === workflowId);
    if (workflow) {
      // Update URL with workflow ID
      router.push(`/workflows?id=${workflowId}`, { scroll: false });
      setSelectedWorkflow(workflow);
      onEditOpen();
    }
  };

  const handleModalClose = (open: boolean) => {
    onEditOpenChange();
    if (!open) {
      // Clear URL parameters when modal closes
      router.push("/workflows", { scroll: false });
      setSelectedWorkflow(null);
    }
  };

  const handleCommunityWorkflowClick = async (workflowId: string) => {
    const communityWorkflow = communityWorkflows.find(
      (w) => w.id === workflowId,
    );
    if (communityWorkflow) {
      const toastId = toast.loading("Creating workflow...");

      try {
        const workflowRequest = {
          title: communityWorkflow.title,
          description: communityWorkflow.description,
          trigger_config: {
            type: "manual" as const,
            enabled: true,
          },
          generate_immediately: true,
        };

        const result = await createWorkflow(workflowRequest);

        if (result.success && result.workflow) {
          toast.success("Workflow created successfully!", { id: toastId });
          selectWorkflow(result.workflow, { autoSend: false });
        }
      } catch (error) {
        toast.error("Error creating workflow", { id: toastId });
        console.error("Workflow creation error:", error);
      }
    }
  };

  const renderWorkflowsGrid = () => {
    if (isLoading) return <WorkflowListSkeleton />;

    if (error) {
      return (
        <div className="flex flex-col items-center justify-center space-y-4 py-12">
          <p className="text-foreground-400">Failed to load workflows</p>
          <Button
            size="sm"
            variant="flat"
            onPress={refetch}
            startContent={<RefreshCw className="h-4 w-4" />}
          >
            Try Again
          </Button>
        </div>
      );
    }

    if (workflows.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center space-y-4 py-12">
          <div className="text-center">
            <h3 className="text-xl font-medium text-zinc-300">
              No workflows yet
            </h3>
          </div>
          <Button color="primary" onPress={onOpen}>
            Create Your First Workflow
          </Button>
        </div>
      );
    }

    return (
      <div className="grid max-w-7xl grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-3">
        {workflows.map((workflow) => (
          <WorkflowCard
            key={workflow.id}
            workflow={workflow}
            onClick={() => handleWorkflowClick(workflow.id)}
          />
        ))}
      </div>
    );
  };

  const renderCommunityWorkflowsGrid = () => {
    if (isLoadingCommunity) return <WorkflowListSkeleton />;

    if (communityError) {
      return (
        <div className="flex flex-col items-center justify-center space-y-4 py-12">
          <p className="text-foreground-400">
            Failed to load community workflows
          </p>
          <Button
            size="sm"
            variant="flat"
            onPress={refetchCommunity}
            startContent={<RefreshCw className="h-4 w-4" />}
          >
            Try Again
          </Button>
        </div>
      );
    }

    if (communityWorkflows.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center space-y-4 py-12">
          <div className="text-center">
            <h3 className="text-xl font-medium text-zinc-300">
              No community workflows yet
            </h3>
            <p className="mt-2 text-sm text-zinc-500">
              Be the first to publish a workflow to the community
            </p>
          </div>
        </div>
      );
    }

    return (
      <div className="grid max-w-7xl grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-3">
        {communityWorkflows.map((workflow: CommunityWorkflow) => (
          <CommunityWorkflowCard
            key={workflow.id}
            workflow={workflow}
            onClick={() => handleCommunityWorkflowClick(workflow.id)}
          />
        ))}
      </div>
    );
  };

  return (
    <div
      className="space-y-10 overflow-y-auto p-4 sm:p-6 md:p-8 lg:px-10"
      ref={pageRef}
    >
      <div className="flex flex-col gap-6 md:gap-7">
        <div className="flex w-full flex-col items-center justify-center">
          <h1 className="mb-3 text-5xl font-normal">Workflows</h1>

          <div className="grid w-full max-w-md grid-cols-2 justify-center gap-2">
            <Link href={"/use-cases"}>
              <Button
                variant="flat"
                size="sm"
                fullWidth
                className="text-zinc-400"
                endContent={<ExternalLink width={16} height={16} />}
              >
                Browse Use Cases
              </Button>
            </Link>

            <Button
              color="primary"
              size="sm"
              variant="flat"
              fullWidth
              onPress={onOpen}
              className="text-primary"
            >
              Create Workflow
            </Button>
          </div>
        </div>

        {renderWorkflowsGrid()}
      </div>

      <div className="mt-16 flex flex-col gap-6">
        <div className="text-center">
          <h1 className="text-4xl font-normal">Explore & Discover</h1>
          <p className="text-md mx-auto max-w-3xl text-zinc-500">
            See what's possible with real examples that actually work!
          </p>
        </div>

        <UseCaseSection dummySectionRef={pageRef} hideUserWorkflows={true} />

        <div className="mt-12 flex flex-col gap-6">
          <div className="text-center">
            <h1 className="text-4xl font-normal">Community Workflows</h1>
            <p className="text-md mx-auto max-w-3xl text-zinc-500">
              Check out what others have built and grab anything that looks
              useful!
            </p>
          </div>

          {renderCommunityWorkflowsGrid()}
        </div>
      </div>

      <CreateWorkflowModal
        isOpen={isOpen}
        onOpenChange={onOpenChange}
        onWorkflowCreated={handleWorkflowCreated}
        onWorkflowListRefresh={refetch}
      />

      <EditWorkflowModal
        isOpen={isEditOpen}
        onOpenChange={handleModalClose}
        onWorkflowUpdated={() => refetch()}
        onWorkflowDeleted={handleWorkflowDeleted}
        onWorkflowListRefresh={refetch}
        workflow={selectedWorkflow}
      />
    </div>
  );
}
