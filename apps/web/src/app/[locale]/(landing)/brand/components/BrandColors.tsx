"use client";

import { Tick01Icon } from "@icons";
import { useState } from "react";

interface ColorCardProps {
  name: string;
  hex: string;
}

function ColorCard({ name, hex }: ColorCardProps) {
  const [copied, setCopied] = useState(false);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      type="button"
      onClick={() => copyToClipboard(hex)}
      className={`group relative overflow-hidden rounded-3xl text-left h-50 flex flex-col justify-end ${hex === "#000000" ? "outline-1 outline-zinc-700 text-white" : "text-black"}`}
      style={{ backgroundColor: hex }}
    >
      <div className="space-y-2 p-4">
        <h3 className="font-semibold">{name}</h3>
        <div className="space-y-1">
          <div
            className={
              "flex items-center justify-between rounded px-2 py-1 text-sm "
            }
          >
            <span>{hex}</span>
            {copied ? (
              <Tick01Icon className="h-4 w-4 text-success" />
            ) : (
              <span className="text-xs opacity-0 group-hover:opacity-100">
                Copy
              </span>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

export function BrandColors() {
  const colors = [
    {
      name: "Primary Blue",
      hex: "#00BBFF",
    },
    {
      name: "Black",
      hex: "#000000",
    },
    {
      name: "White",
      hex: "#FFFFFF",
    },
  ];

  return (
    <div>
      <div className="mb-8">
        <h2 className="mb-3 text-3xl font-medium">Brand Colors</h2>
        <p className="text-foreground-600 dark:text-foreground-400">
          Our primary brand colors. Click any color to copy its hex or RGB
          value.
        </p>
      </div>
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {colors.map((color) => (
          <ColorCard key={color.name} {...color} />
        ))}
      </div>
    </div>
  );
}
