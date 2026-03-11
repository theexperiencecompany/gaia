"use client";

import { DownloadAsset } from "./DownloadAsset";

export function BrandAssets() {
  return (
    <div className="space-y-24">
      {/* GAIA Logo Section */}
      <section>
        <div className="mb-8 text-center">
          <h2 className="mb-3 text-3xl font-medium">GAIA Logo</h2>
          <p className="text-foreground-600 dark:text-foreground-400">
            The primary GAIA brand mark
          </p>
        </div>
        <div className="flex justify-center">
          <div className="w-full max-w-md">
            <DownloadAsset
              name="GAIA Logo"
              backgroundColor="dark"
              imagePath="/brand/gaia_logo.svg"
              downloadOptions={[
                { format: ".svg", path: "/brand/gaia_logo.svg" },
                { format: ".png", path: "/brand/gaia_logo.png" },
              ]}
              imageAlt="GAIA Logo"
            />
          </div>
        </div>
      </section>

      {/* GAIA Wordmarks Section */}
      <section>
        <div className="mb-8 text-center">
          <h2 className="mb-3 text-3xl font-medium">GAIA Wordmarks</h2>
          <p className="text-foreground-600 dark:text-foreground-400">
            Full GAIA wordmarks for various backgrounds
          </p>
        </div>
        <div className="grid gap-8 sm:grid-cols-2">
          <DownloadAsset
            name="GAIA Wordmark Black"
            imagePath="/brand/gaia_wordmark_black.png"
            downloadOptions={[
              { format: ".png", path: "/brand/gaia_wordmark_black.png" },
            ]}
            imageAlt="GAIA Wordmark in black"
            backgroundColor="light"
          />
          <DownloadAsset
            name="GAIA Wordmark White"
            imagePath="/brand/gaia_wordmark_white.png"
            downloadOptions={[
              { format: ".png", path: "/brand/gaia_wordmark_white.png" },
            ]}
            imageAlt="GAIA Wordmark in white"
            backgroundColor="dark"
          />
        </div>
      </section>

      {/* Experience Logo Section */}
      <section>
        <div className="mb-8 text-center">
          <h2 className="mb-3 text-3xl font-medium">
            The Experience Company Logo
          </h2>
          <p className="text-foreground-600 dark:text-foreground-400">
            The Experience Company brand mark in multiple variants
          </p>
        </div>
        <div className="grid gap-8 sm:grid-cols-2">
          <DownloadAsset
            name="Experience Logo Black"
            imagePath="/brand/experience_logo_black.svg"
            downloadOptions={[
              { format: ".svg", path: "/brand/experience_logo_black.svg" },
              { format: ".png", path: "/brand/experience_logo_black.png" },
            ]}
            imageAlt="The Experience Company Logo in black"
            backgroundColor="light"
          />
          <DownloadAsset
            name="Experience Logo White"
            imagePath="/brand/experience_logo_white.svg"
            downloadOptions={[
              { format: ".svg", path: "/brand/experience_logo_white.svg" },
              { format: ".png", path: "/brand/experience_logo_white.png" },
            ]}
            imageAlt="The Experience Company Logo in white"
            backgroundColor="dark"
          />
        </div>
      </section>

      {/* Experience Wordmarks Section */}
      <section>
        <div className="mb-8 text-center">
          <h2 className="mb-3 text-3xl font-medium">Experience Wordmarks</h2>
          <p className="text-foreground-600 dark:text-foreground-400">
            "Experience" wordmark variations
          </p>
        </div>
        <div className="grid gap-8 sm:grid-cols-2">
          <DownloadAsset
            name="Experience Wordmark Black"
            imagePath="/brand/experience_wordmark_black.png"
            downloadOptions={[
              { format: ".png", path: "/brand/experience_wordmark_black.png" },
            ]}
            imageAlt="Experience wordmark in black"
            backgroundColor="light"
          />
          <DownloadAsset
            name="Experience Wordmark White"
            imagePath="/brand/experience_wordmark_white.png"
            downloadOptions={[
              { format: ".png", path: "/brand/experience_wordmark_white.png" },
            ]}
            imageAlt="Experience wordmark in white"
            backgroundColor="dark"
          />
        </div>
      </section>

      {/* Experience Full Wordmarks Section */}
      <section>
        <div className="mb-8 text-center">
          <h2 className="mb-3 text-3xl font-medium">
            The Experience Company Full Wordmarks
          </h2>
          <p className="text-foreground-600 dark:text-foreground-400">
            Complete "The Experience Company" wordmark
          </p>
        </div>
        <div className="grid gap-8 sm:grid-cols-2">
          <DownloadAsset
            name="Full Wordmark Black"
            imagePath="/brand/experience_full_wordmark_black.png"
            downloadOptions={[
              {
                format: ".png",
                path: "/brand/experience_full_wordmark_black.png",
              },
            ]}
            imageAlt="The Experience Company full wordmark in black"
            backgroundColor="light"
          />
          <DownloadAsset
            name="Full Wordmark White"
            imagePath="/brand/experience_full_wordmark_white.png"
            downloadOptions={[
              {
                format: ".png",
                path: "/brand/experience_full_wordmark_white.png",
              },
            ]}
            imageAlt="The Experience Company full wordmark in white"
            backgroundColor="dark"
          />
        </div>
      </section>
    </div>
  );
}
