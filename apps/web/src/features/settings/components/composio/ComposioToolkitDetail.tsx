"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { Skeleton } from "@heroui/skeleton";
import { CheckmarkCircle02Icon, Delete02Icon, Link01Icon } from "@icons";
import { useState } from "react";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import type {
  ComposioCatalogEntry,
  ComposioToolkitDetailResponse,
} from "@/features/settings/api/composioSetupApi";
import {
  useComposioToolkit,
  useComposioToolkitActions,
} from "@/features/settings/hooks/useComposioToolkits";

interface ComposioToolkitDetailProps {
  slug: string;
}

/** What enabling one toolkit takes, and the button that does it. */
export function ComposioToolkitDetail({ slug }: ComposioToolkitDetailProps) {
  const { data: detail, isLoading, error } = useComposioToolkit(slug);
  const [values, setValues] = useState<Record<string, string>>({});

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-12 w-full rounded-2xl" />
        <Skeleton className="h-24 w-full rounded-2xl" />
      </div>
    );
  }
  if (error || !detail) {
    return (
      <p className="text-sm text-zinc-400">
        Couldn&apos;t load this toolkit from Composio.
      </p>
    );
  }

  const { toolkit } = detail;
  const missing = detail.fields.some(
    (field) => field.required && !values[field.name]?.trim(),
  );
  const canEnable =
    detail.auth_scheme !== null &&
    (toolkit.status === "available" ||
      (toolkit.status === "built_in" && !toolkit.set_up));

  return (
    <div className="flex flex-col gap-4">
      <ToolkitHeader toolkit={toolkit} />

      <p className="text-sm text-zinc-400">{toolkit.description}</p>

      <div className="rounded-2xl bg-zinc-900 p-3 text-sm text-zinc-400">
        {authSetupNote(detail)}
        {toolkit.status !== "built_in" && detail.auth_scheme !== null && (
          <span className="mt-2 block text-zinc-500">
            Added from the Composio catalog, so it has no triggers; workflows
            can still use its tools.
          </span>
        )}
      </div>

      {canEnable &&
        detail.fields.map((field) => (
          <Input
            key={field.name}
            label={field.display_name}
            description={field.description}
            isRequired={field.required}
            type={field.is_secret ? "password" : "text"}
            size="sm"
            value={values[field.name] ?? ""}
            onValueChange={(value) =>
              setValues((current) => ({ ...current, [field.name]: value }))
            }
          />
        ))}

      <ToolkitActions
        slug={slug}
        toolkit={toolkit}
        credentials={values}
        canSubmit={canEnable && !missing}
      />
    </div>
  );
}

/** How users will sign in once the toolkit is enabled, and what the admin must provide. */
function authSetupNote(detail: ComposioToolkitDetailResponse): string {
  const { name } = detail.toolkit;
  if (detail.auth_scheme === null)
    return "This app needs no sign-in, which GAIA can't connect yet.";
  if (detail.composio_managed)
    return "Users sign in through Composio's own app. Nothing to fill in.";
  if (detail.fields.length === 0)
    return `Each user enters their own ${name} credentials when they connect.`;
  return `Composio has no shared app for ${name}. Create one with ${name} and paste its details below.`;
}

function ToolkitHeader({ toolkit }: { toolkit: ComposioCatalogEntry }) {
  return (
    <div className="flex items-center gap-3">
      <IntegrationIcon
        integrationId={toolkit.slug}
        iconUrl={toolkit.logo}
        size={40}
      />
      <div className="min-w-0">
        <h3 className="truncate text-base font-medium text-zinc-100">
          {toolkit.name}
        </h3>
        <p className="text-xs text-zinc-500">
          {toolkit.tools_count} tools
          {toolkit.categories.length > 0 &&
            ` in ${toolkit.categories.join(", ")}`}
        </p>
      </div>
    </div>
  );
}

interface ToolkitActionsProps {
  slug: string;
  toolkit: ComposioCatalogEntry;
  credentials: Record<string, string>;
  canSubmit: boolean;
}

function ToolkitActions({
  slug,
  toolkit,
  credentials,
  canSubmit,
}: ToolkitActionsProps) {
  const { enable, disable } = useComposioToolkitActions();
  const { name } = toolkit;

  return (
    <div className="flex items-center justify-end gap-2">
      {toolkit.status === "enabled" && (
        <Button
          size="sm"
          variant="flat"
          color="danger"
          startContent={<Delete02Icon className="size-4" />}
          isLoading={disable.isPending}
          onPress={() => disable.mutate({ slug, name })}
        >
          Remove
        </Button>
      )}
      {toolkit.set_up ? (
        <Chip
          size="sm"
          variant="flat"
          color="success"
          startContent={<CheckmarkCircle02Icon className="size-3.5" />}
        >
          Ready to connect
        </Chip>
      ) : (
        <Button
          size="sm"
          color="primary"
          isDisabled={!canSubmit}
          isLoading={enable.isPending}
          startContent={!enable.isPending && <Link01Icon className="size-4" />}
          onPress={() => enable.mutate({ slug, name, credentials })}
        >
          {toolkit.status === "built_in" ? "Set up" : "Enable"}
        </Button>
      )}
    </div>
  );
}
