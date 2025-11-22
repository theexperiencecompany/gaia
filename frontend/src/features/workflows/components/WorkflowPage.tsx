"use client";

import { Button } from "@heroui/button";
import { useDisclosure } from "@heroui/modal";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ReactElement,
  ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import React from "react";

import WorkflowsHeader from "@/components/layout/headers/WorkflowsHeader";
import UseCaseSection from "@/features/use-cases/components/UseCaseSection";
import { UseCase } from "@/features/use-cases/types";
import { useHeader } from "@/hooks/layout/useHeader";
import {
  IconProps,
  RedoIcon,
} from "@/icons";

import { CommunityWorkflow, Workflow, workflowApi } from "../api/workflowApi";
import { useWorkflows } from "../hooks";
import CommunityWorkflowCard from "./CommunityWorkflowCard";
import CreateWorkflowModal from "./CreateWorkflowModal";
import EditWorkflowModal from "./EditWorkflowModal";
import WorkflowCard from "./WorkflowCard";
import { WorkflowListSkeleton } from "./WorkflowSkeletons";

export default function WorkflowPage() {
  const pageRef = useRef(null);
  const router = useRouter();
  const searchParams = useSearchParams();
  const workflowId = searchParams.get("id");
  const { setHeader } = useHeader();

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
  const [exploreWorkflows, setExploreWorkflows] = useState<UseCase[]>([]);
  const [isLoadingExplore, setIsLoadingExplore] = useState(false);

  const [communityWorkflows, setCommunityWorkflows] = useState<
    CommunityWorkflow[]
  >([]);
  const [isLoadingCommunity, setIsLoadingCommunity] = useState(false);
  const [communityError, setCommunityError] = useState<string | null>(null);

  // Convert CommunityWorkflow to UseCase format
  const convertToUseCase = (workflow: CommunityWorkflow): UseCase => ({
    title: workflow.title,
    description: workflow.description,
    action_type: "workflow",
    integrations:
      workflow.steps
        ?.map((s) => s.tool_category)
        .filter((v, i, a) => a.indexOf(v) === i) || [],
    categories: workflow.categories || ["featured"],
    published_id: workflow.id,
    slug: workflow.id,
    steps: workflow.steps,
    creator: workflow.creator,
  });

  const loadExploreWorkflows = useCallback(async () => {
    setIsLoadingExplore(true);
    try {
      const response = await workflowApi.getExploreWorkflows(25, 0);
      const useCases = response.workflows.map(convertToUseCase);
      setExploreWorkflows(useCases);
    } catch (error) {
      console.error("Error loading explore workflows:", error);
    } finally {
      setIsLoadingExplore(false);
    }
  }, []);

  const loadCommunityWorkflows = useCallback(async () => {
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

  // Memoize the header component to prevent recreating on every render
  const headerComponent = useMemo(
    () => <WorkflowsHeader onCreateWorkflow={onOpen} />,
    [onOpen],
  );

  // Use useLayoutEffect to set header synchronously before paint (faster)
  // Don't include setHeader in deps - it's stable from Zustand
  useLayoutEffect(() => {
    setHeader(headerComponent);
    return () => setHeader(null);
  }, [headerComponent]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    loadExploreWorkflows();
    loadCommunityWorkflows();
  }, [loadExploreWorkflows, loadCommunityWorkflows]);

  useEffect(() => {
    if (workflowId && workflows.length > 0) {
      const workflow = workflows.find((w) => w.id === workflowId);
      if (workflow) {
        setSelectedWorkflow(workflow);
        onEditOpen();
      }
    }
  }, [workflowId, workflows, onEditOpen]);

  const handleWorkflowCreated = useCallback(() => {
    refetch();
  }, [refetch]);

  const handleWorkflowDeleted = useCallback(
    (workflowId: string) => {
      console.log("Workflow deleted:", workflowId);
      refetch();
    },
    [refetch],
  );

  const handleWorkflowClick = (workflowId: string) => {
    const workflow = workflows.find((w) => w.id === workflowId);
    if (workflow) {
      router.push(`/workflows?id=${workflowId}`, { scroll: false });
      setSelectedWorkflow(workflow);
      onEditOpen();
    }
  };

  const handleModalClose = (open: boolean) => {
    onEditOpenChange();
    if (!open) {
      router.push("/workflows", { scroll: false });
      setSelectedWorkflow(null);
    }
  };

  const handleCommunityWorkflowClick = (workflowId: string) => {
    router.push(`/use-cases/${workflowId}`);
  };

  const renderGrid = <T extends { id: string }>(
    items: T[],
    isLoading: boolean,
    error: string | null,
    emptyTitle: string,
    emptyDescription: string,
    onRefetch: () => void,
    renderItem: (item: T) => ReactNode,
    emptyAction?: ReactNode,
  ) => {
    if (isLoading) return <WorkflowListSkeleton />;

    if (error) {
      return (
        <div className="flex flex-col items-center justify-center space-y-4 py-1">
          <p className="text-foreground-400">{error}</p>
          <Button
            size="sm"
            variant="flat"
            onPress={onRefetch}
            startContent={<RedoIcon className="h-4 w-4" />}
          >
            Try Again
          </Button>
        </div>
      );
    }

    if (items.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/50 py-16">
          <div className="text-center">
            <h3 className="text-lg font-medium text-zinc-300">{emptyTitle}</h3>
            <p className="mt-2 text-sm text-zinc-500">{emptyDescription}</p>
          </div>
          {emptyAction}
        </div>
      );
    }

    return (
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-3">
        {items.map((item) => renderItem(item))}
      </div>
    );
  };

  const renderSection = (
    title: string,
    description: string,
    children: ReactNode,
    icon?: ReactElement<IconProps>,
  ) => (
    <div className="mt-12 flex flex-col gap-3">
      <div className="flex flex-col space-y-1">
        <div className="flex items-center gap-2">
          {icon && <span> {React.cloneElement(icon)}</span>}
          <h2 className="text-2xl font-medium text-zinc-100">{title}</h2>
        </div>
        <p className="font-light text-zinc-500">{description}</p>
      </div>
      {children}
    </div>
  );

  const showAnySkeleton = isLoading || isLoadingExplore || isLoadingCommunity;

  return (
    <div className="space-y-8 overflow-y-auto p-4 sm:p-6 md:p-8" ref={pageRef}>
      {showAnySkeleton ? (
        <>
          <WorkflowListSkeleton />
          {renderSection(
            "Explore & Discover",
            "See what's possible with real examples that actually work!",
            <WorkflowListSkeleton />,
          )}
          {renderSection(
            "Community Workflows",
            "Check out what others have built and grab anything that looks useful!",
            <WorkflowListSkeleton />,
          )}
        </>
      ) : (
        <>
          <div className="flex flex-col gap-6">
            {renderGrid(
              workflows,
              false,
              error ? "Failed to load workflows" : null,
              "No workflows yet",
              "Create your first workflow to get started",
              refetch,
              (workflow) => (
                <WorkflowCard
                  key={workflow.id}
                  workflow={workflow}
                  onClick={() => handleWorkflowClick(workflow.id)}
                />
              ),
              <Button color="primary" variant="flat" onPress={onOpen}>
                Create Your First Workflow
              </Button>,
            )}
          </div>

          {renderSection(
            "Explore & Discover",
            "See what's possible with real examples that actually work!",
            <UseCaseSection
              centered={false}
              dummySectionRef={pageRef}
              hideUserWorkflows={true}
              exploreWorkflows={exploreWorkflows}
              isLoadingExplore={isLoadingExplore}
            />,
          )}

          {renderSection(
            "Community Workflows",
            "Check out what others have built and grab anything that looks useful!",
            renderGrid(
              communityWorkflows,
              false,
              communityError,
              "No community workflows yet",
              "Be the first to publish a workflow to the community",
              loadCommunityWorkflows,
              (workflow) => (
                <CommunityWorkflowCard
                  key={workflow.id}
                  workflow={workflow}
                  onClick={() => handleCommunityWorkflowClick(workflow.id)}
                />
              ),
            ),
          )}
        </>
      )}

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
