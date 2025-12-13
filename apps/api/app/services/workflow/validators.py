"""Workflow validation utilities for GAIA workflow system."""

from app.models.workflow_models import Workflow
from pydantic import ValidationError


class WorkflowValidator:
    """Simple validator for basic workflow checks."""

    @staticmethod
    def validate_for_execution(workflow: Workflow) -> None:
        """Basic validation for workflow execution."""
        errors = []

        if not workflow.activated:
            errors.append("Workflow is deactivated")

        if not workflow.steps:
            errors.append("Workflow has no steps defined")

        if not workflow.trigger_config:
            errors.append("Missing trigger configuration")

        if errors:
            raise ValidationError(f"Workflow validation failed: {'; '.join(errors)}")
