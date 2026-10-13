"use client";

import { Tab, Tabs } from "@heroui/tabs";
import { ReferralsView } from "@/features/referrals/components/page/layouts";
import {
  COPY_VARIANTS,
  FIXTURE_ME,
  FIXTURE_SUGGESTIONS,
  fixtureSender,
  GALLERY_STATES,
  GALLERY_VIEWS,
  type GalleryView,
  LAYOUT_VARIANTS,
} from "./fixtures";
import { GalleryPreview } from "./GalleryPreview";
import { useGalleryParams } from "./galleryParams";

const VIEW_LABELS: Record<GalleryView, string> = {
  page: "Settings page",
  landing: "Landing",
  og: "OG image",
};

interface ControlProps {
  label: string;
  options: readonly string[];
  selected: string;
  onChange: (value: string) => void;
}

function Control({ label, options, selected, onChange }: ControlProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-14 text-xs text-zinc-500">{label}</span>
      <Tabs
        size="sm"
        aria-label={label}
        selectedKey={selected}
        onSelectionChange={(key) => onChange(String(key))}
      >
        {options.map((option) => (
          <Tab key={option} title={option} />
        ))}
      </Tabs>
    </div>
  );
}

export function ReferralsGallery() {
  const { view, layout, copy, state, set } = useGalleryParams();
  const me = FIXTURE_ME[state];

  return (
    <div className="dark min-h-dvh bg-primary-bg text-foreground">
      <div className="sticky top-0 z-20 flex flex-wrap items-center gap-x-6 gap-y-2 bg-primary-bg/90 px-6 py-3 backdrop-blur-xl">
        <Tabs
          size="sm"
          aria-label="Surface"
          selectedKey={view}
          onSelectionChange={(key) => set("view", String(key))}
        >
          {GALLERY_VIEWS.map((v) => (
            <Tab key={v} title={VIEW_LABELS[v]} />
          ))}
        </Tabs>
        <Control
          label="Copy"
          options={COPY_VARIANTS}
          selected={copy}
          onChange={(v) => set("copy", v)}
        />
        {view === "page" && (
          <>
            <Control
              label="Layout"
              options={LAYOUT_VARIANTS}
              selected={layout}
              onChange={(v) => set("layout", v)}
            />
            <Control
              label="State"
              options={GALLERY_STATES}
              selected={state}
              onChange={(v) => set("state", v)}
            />
          </>
        )}
      </div>
      <div className="px-4 py-10 sm:px-6">
        {view === "page" ? (
          <ReferralsView
            layout={layout}
            me={me}
            suggestions={FIXTURE_SUGGESTIONS}
            send={fixtureSender}
            copyVariant={copy}
          />
        ) : (
          <GalleryPreview view={view} copyVariant={copy} />
        )}
      </div>
    </div>
  );
}
