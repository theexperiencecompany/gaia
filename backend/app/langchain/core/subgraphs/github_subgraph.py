"""GitHub plan-and-execute subgraph built from reusable configuration."""

import asyncio
from typing import Sequence

from app.agents.prompts.github_node_prompts import (
    ASSIGNEE_MANAGEMENT_PROMPT,
    BRANCH_MANAGEMENT_PROMPT,
    COMMENT_MANAGEMENT_PROMPT,
    COMMIT_OPERATIONS_PROMPT,
    ISSUE_MANAGEMENT_PROMPT,
    LABEL_MANAGEMENT_PROMPT,
    PULL_REQUEST_MANAGEMENT_PROMPT,
    REPOSITORY_OPERATIONS_PROMPT,
)
from app.config.loggers import langchain_logger as logger
from app.langchain.core.framework.plan_and_execute import (
    OrchestratorNodeConfig,
    OrchestratorSubgraphConfig,
    build_orchestrator_subgraph,
)
from app.services.composio.composio_service import get_composio_service
from langchain_core.language_models import LanguageModelLike
from langgraph.graph.state import CompiledStateGraph


async def get_node_configs() -> Sequence[OrchestratorNodeConfig]:
    """Get the list of GitHub node configurations."""
    composio_service = get_composio_service()

    (
        pull_request_tools,
        issue_tools,
        label_tools,
        assignee_tools,
        comment_tools,
        commit_tools,
        repository_tools,
        branch_tools,
    ) = await asyncio.gather(
        composio_service.get_tools_by_name(
            [
                "GITHUB_CREATE_PULL_REQUEST",
                "GITHUB_GET_PULL_REQUEST",
                "GITHUB_LIST_PULL_REQUESTS",
                "GITHUB_UPDATE_PULL_REQUEST",
                "GITHUB_CLOSE_PULL_REQUEST",
                "GITHUB_MERGE_PULL_REQUEST",
                "GITHUB_LIST_PULL_REQUEST_COMMITS",
                "GITHUB_LIST_PULL_REQUEST_FILES",
                "GITHUB_REQUEST_PULL_REQUEST_REVIEWERS",
                "GITHUB_LIST_PULL_REQUEST_REVIEWS",
                "GITHUB_SUBMIT_PULL_REQUEST_REVIEW",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GITHUB_CREATE_ISSUE",
                "GITHUB_GET_ISSUE",
                "GITHUB_LIST_ISSUES",
                "GITHUB_UPDATE_ISSUE",
                "GITHUB_CLOSE_ISSUE",
                "GITHUB_LOCK_ISSUE",
                "GITHUB_UNLOCK_ISSUE",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GITHUB_CREATE_LABEL",
                "GITHUB_GET_LABEL",
                "GITHUB_LIST_LABELS_FOR_REPO",
                "GITHUB_UPDATE_LABEL",
                "GITHUB_DELETE_LABEL",
                "GITHUB_ADD_LABELS_TO_ISSUE",
                "GITHUB_REMOVE_LABEL_FROM_ISSUE",
                "GITHUB_LIST_LABELS_FOR_ISSUE",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GITHUB_ADD_ASSIGNEES_TO_ISSUE",
                "GITHUB_REMOVE_ASSIGNEES_FROM_ISSUE",
                "GITHUB_LIST_ASSIGNEES",
                "GITHUB_GET_USER",
                "GITHUB_LIST_REPO_COLLABORATORS",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GITHUB_CREATE_ISSUE_COMMENT",
                "GITHUB_LIST_ISSUE_COMMENTS",
                "GITHUB_CREATE_PULL_REQUEST_COMMENT",
                "GITHUB_LIST_PULL_REQUEST_COMMENTS",
                "GITHUB_CREATE_COMMIT_COMMENT",
                "GITHUB_LIST_COMMIT_COMMENTS",
                "GITHUB_UPDATE_COMMENT",
                "GITHUB_DELETE_COMMENT",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GITHUB_GET_COMMIT",
                "GITHUB_LIST_COMMITS",
                "GITHUB_COMPARE_COMMITS",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GITHUB_GET_REPOSITORY",
                "GITHUB_LIST_USER_REPOSITORIES",
                "GITHUB_LIST_ORGANIZATION_REPOSITORIES",
                "GITHUB_GET_REPO_CONTENT",
                "GITHUB_CREATE_FORK",
                "GITHUB_STAR_A_REPOSITORY",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GITHUB_GET_BRANCH",
                "GITHUB_LIST_BRANCHES",
                "GITHUB_MERGE_BRANCH",
                "GITHUB_GET_BRANCH_PROTECTION",
            ]
        ),
    )

    return (
        OrchestratorNodeConfig(
            name="pull_request_management",
            description="Create, manage, review, and merge pull requests with full PR lifecycle support",
            system_prompt=PULL_REQUEST_MANAGEMENT_PROMPT,
            tools=pull_request_tools,
        ),
        OrchestratorNodeConfig(
            name="issue_management",
            description="Track bugs, features, and tasks through GitHub issues with full lifecycle management",
            system_prompt=ISSUE_MANAGEMENT_PROMPT,
            tools=issue_tools,
        ),
        OrchestratorNodeConfig(
            name="label_management",
            description="Categorize and organize issues and PRs using labels with taxonomy management",
            system_prompt=LABEL_MANAGEMENT_PROMPT,
            tools=label_tools,
        ),
        OrchestratorNodeConfig(
            name="assignee_management",
            description="Manage responsibilities, assign collaborators, and retrieve user information",
            system_prompt=ASSIGNEE_MANAGEMENT_PROMPT,
            tools=assignee_tools,
        ),
        OrchestratorNodeConfig(
            name="comment_management",
            description="Add, update, and manage comments on PRs, issues, and commits",
            system_prompt=COMMENT_MANAGEMENT_PROMPT,
            tools=comment_tools,
        ),
        OrchestratorNodeConfig(
            name="commit_operations",
            description="Inspect commit history, compare changes, and analyze code evolution",
            system_prompt=COMMIT_OPERATIONS_PROMPT,
            tools=commit_tools,
        ),
        OrchestratorNodeConfig(
            name="repository_operations",
            description="Browse repositories, retrieve contents, fork, and star repositories",
            system_prompt=REPOSITORY_OPERATIONS_PROMPT,
            tools=repository_tools,
        ),
        OrchestratorNodeConfig(
            name="branch_management",
            description="Manage code branches, branch protection, and merge operations",
            system_prompt=BRANCH_MANAGEMENT_PROMPT,
            tools=branch_tools,
        ),
    )


async def create_github_subgraph(llm: LanguageModelLike) -> CompiledStateGraph:
    """Factory function to create and compile the GitHub sub-agent subgraph.

    Args:
        llm: Language model to use for the subgraph

    Returns:
        CompiledStateGraph with automatic message filtering and cleanup
    """
    logger.info("Creating GitHub subgraph using plan-and-execute framework")

    config = OrchestratorSubgraphConfig(
        provider_name="GitHub",
        agent_name="github_agent",
        node_configs=await get_node_configs(),
        llm=llm,
    )

    graph = build_orchestrator_subgraph(config)
    logger.info("GitHub subgraph created successfully")

    return graph
