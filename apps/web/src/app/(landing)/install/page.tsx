import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Install GAIA CLI",
  description:
    "Install the GAIA CLI tool to quickly set up and manage your self-hosted GAIA instance. One command to get started with your AI assistant.",
  path: "/install",
  keywords: [
    "GAIA CLI",
    "Install GAIA",
    "Self-hosted Setup",
    "Command Line",
    "CLI Tool",
    "Quick Install",
    "GAIA Setup",
    "Developer Tools",
  ],
});

export default function InstallPage() {
  const webPageSchema = generateWebPageSchema(
    "Install GAIA CLI",
    "Quick installation guide for the GAIA CLI tool",
    `${siteConfig.url}/install`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Install", url: `${siteConfig.url}/install` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Install", url: `${siteConfig.url}/install` },
  ]);

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema]} />
      <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-950 dark:to-gray-900">
        <div className="mx-auto max-w-4xl px-4 py-16 sm:px-6 lg:px-8">
          {/* Hero Section */}
          <div className="text-center">
            <h1 className="text-4xl font-bold tracking-tight text-gray-900 dark:text-white sm:text-5xl">
              Install GAIA CLI
            </h1>
            <p className="mt-4 text-lg text-gray-600 dark:text-gray-400">
              Set up your self-hosted GAIA instance with a single command
            </p>
          </div>

          {/* Quick Install Section */}
          <div className="mt-12 rounded-2xl border border-gray-200 bg-white p-8 shadow-sm dark:border-gray-800 dark:bg-gray-900">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
              Quick Install
            </h2>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              Run this command in your terminal to install the GAIA CLI:
            </p>
            <div className="mt-4 rounded-lg bg-gray-950 p-4">
              <code className="text-sm text-green-400">
                curl -fsSL https://heygaia.io/install.sh | sh
              </code>
            </div>
            <p className="mt-4 text-sm text-gray-600 dark:text-gray-400">
              Then run{" "}
              <code className="rounded bg-gray-100 px-2 py-1 text-sm dark:bg-gray-800">
                gaia init
              </code>{" "}
              to set up GAIA
            </p>
          </div>

          {/* Alternative Methods */}
          <div className="mt-8 rounded-2xl border border-gray-200 bg-white p-8 shadow-sm dark:border-gray-800 dark:bg-gray-900">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
              Alternative Installation Methods
            </h2>

            <div className="mt-4 space-y-4">
              <div>
                <h3 className="font-medium text-gray-900 dark:text-white">
                  Using npx (no install)
                </h3>
                <div className="mt-2 rounded-lg bg-gray-950 p-4">
                  <code className="text-sm text-green-400">
                    npx @heygaia/cli init
                  </code>
                </div>
              </div>

              <div>
                <h3 className="font-medium text-gray-900 dark:text-white">
                  Using Bun
                </h3>
                <div className="mt-2 rounded-lg bg-gray-950 p-4">
                  <code className="text-sm text-green-400">
                    bunx @heygaia/cli init
                  </code>
                </div>
              </div>

              <div>
                <h3 className="font-medium text-gray-900 dark:text-white">
                  Global Install
                </h3>
                <div className="mt-2 rounded-lg bg-gray-950 p-4">
                  <code className="text-sm text-green-400">
                    bun install -g @heygaia/cli
                  </code>
                </div>
                <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                  or with npm:{" "}
                  <code className="rounded bg-gray-100 px-2 py-1 text-sm dark:bg-gray-800">
                    npm install -g @heygaia/cli
                  </code>
                </p>
              </div>
            </div>
          </div>

          {/* What It Does */}
          <div className="mt-8 rounded-2xl border border-gray-200 bg-white p-8 shadow-sm dark:border-gray-800 dark:bg-gray-900">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
              What the CLI Does
            </h2>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              The interactive wizard guides you through:
            </p>
            <ol className="mt-4 space-y-2 text-sm text-gray-700 dark:text-gray-300">
              <li className="flex items-start">
                <span className="mr-2 font-semibold text-blue-600 dark:text-blue-400">
                  1.
                </span>
                Prerequisites check (Git, Docker, Mise)
              </li>
              <li className="flex items-start">
                <span className="mr-2 font-semibold text-blue-600 dark:text-blue-400">
                  2.
                </span>
                Repository cloning with progress tracking
              </li>
              <li className="flex items-start">
                <span className="mr-2 font-semibold text-blue-600 dark:text-blue-400">
                  3.
                </span>
                Tool installation (Node.js, Python, uv, Nx)
              </li>
              <li className="flex items-start">
                <span className="mr-2 font-semibold text-blue-600 dark:text-blue-400">
                  4.
                </span>
                Interactive environment variable configuration
              </li>
              <li className="flex items-start">
                <span className="mr-2 font-semibold text-blue-600 dark:text-blue-400">
                  5.
                </span>
                Project setup and dependency installation
              </li>
              <li className="flex items-start">
                <span className="mr-2 font-semibold text-blue-600 dark:text-blue-400">
                  6.
                </span>
                Service startup
              </li>
            </ol>
          </div>

          {/* Available Commands */}
          <div className="mt-8 rounded-2xl border border-gray-200 bg-white p-8 shadow-sm dark:border-gray-800 dark:bg-gray-900">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
              Available Commands
            </h2>
            <div className="mt-4 space-y-3">
              <div className="flex items-start border-b border-gray-100 pb-3 dark:border-gray-800">
                <code className="min-w-[140px] rounded bg-gray-100 px-2 py-1 text-sm font-medium dark:bg-gray-800">
                  gaia init
                </code>
                <p className="ml-4 text-sm text-gray-600 dark:text-gray-400">
                  Full setup from scratch
                </p>
              </div>
              <div className="flex items-start border-b border-gray-100 pb-3 dark:border-gray-800">
                <code className="min-w-[140px] rounded bg-gray-100 px-2 py-1 text-sm font-medium dark:bg-gray-800">
                  gaia setup
                </code>
                <p className="ml-4 text-sm text-gray-600 dark:text-gray-400">
                  Configure existing repo
                </p>
              </div>
              <div className="flex items-start border-b border-gray-100 pb-3 dark:border-gray-800">
                <code className="min-w-[140px] rounded bg-gray-100 px-2 py-1 text-sm font-medium dark:bg-gray-800">
                  gaia status
                </code>
                <p className="ml-4 text-sm text-gray-600 dark:text-gray-400">
                  Check service health
                </p>
              </div>
              <div className="flex items-start border-b border-gray-100 pb-3 dark:border-gray-800">
                <code className="min-w-[140px] rounded bg-gray-100 px-2 py-1 text-sm font-medium dark:bg-gray-800">
                  gaia start
                </code>
                <p className="ml-4 text-sm text-gray-600 dark:text-gray-400">
                  Start GAIA services
                </p>
              </div>
              <div className="flex items-start">
                <code className="min-w-[140px] rounded bg-gray-100 px-2 py-1 text-sm font-medium dark:bg-gray-800">
                  gaia stop
                </code>
                <p className="ml-4 text-sm text-gray-600 dark:text-gray-400">
                  Stop all services
                </p>
              </div>
            </div>
          </div>

          {/* Links */}
          <div className="mt-8 flex justify-center gap-4">
            <a
              href="https://docs.heygaia.io/self-hosting/cli-setup"
              className="rounded-lg bg-blue-600 px-6 py-3 text-sm font-medium text-white hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600"
            >
              Read Full Documentation
            </a>
            <a
              href="https://github.com/heygaia/gaia"
              className="rounded-lg border border-gray-300 px-6 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
            >
              View on GitHub
            </a>
          </div>
        </div>
      </div>
    </>
  );
}
