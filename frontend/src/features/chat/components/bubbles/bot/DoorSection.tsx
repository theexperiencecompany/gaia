import { Chip } from "@heroui/chip";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock,
  DoorClosed,
  DoorOpen,
  Lock,
  LockOpen,
  Radio,
  Server,
  ShieldCheck,
  XCircle,
  Zap,
} from "lucide-react";
import React from "react";

import type { DoorData } from "@/types";

interface DoorSectionProps {
  door_data: DoorData;
}

export default function DoorSection({ door_data }: DoorSectionProps) {
  const { success, action, is_open, message, timestamp, details } = door_data;

  // Determine theme based on door state
  const doorTheme = is_open
    ? {
        gradient: "from-emerald-500/80 to-teal-600/80",
        iconColor: "#10B981",
        accentColor: "#34D399",
        bgOverlay: "bg-emerald-500/10",
        statusBg: "bg-emerald-500/30",
        pulseColor: "bg-emerald-400",
        ringColor: "bg-emerald-500",
      }
    : {
        gradient: "from-slate-600/80 to-slate-700/80",
        iconColor: "#94A3B8",
        accentColor: "#CBD5E1",
        bgOverlay: "bg-slate-500/10",
        statusBg: "bg-slate-500/30",
        pulseColor: "bg-slate-400",
        ringColor: "bg-slate-500",
      };

  const errorTheme = {
    gradient: "from-red-500/80 to-red-600/80",
    iconColor: "#EF4444",
    accentColor: "#F87171",
    bgOverlay: "bg-red-500/10",
    statusBg: "bg-red-500/30",
    pulseColor: "bg-red-400",
    ringColor: "bg-red-500",
  };

  const currentTheme = success ? doorTheme : errorTheme;

  const formatTime = (timestamp: string | undefined) => {
    if (!timestamp) return null;
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const formatFullTime = (timestamp: string | undefined) => {
    if (!timestamp) return null;
    const date = new Date(timestamp);
    return date.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  // Get HTTP status code based on success
  const getStatusCode = () => {
    if (success) return 200;
    return 500; // Internal Server Error for failed operations
  };

  const statusCode = getStatusCode();
  const statusText = success ? "OK" : "ERROR";

  return (
    <div
      className={`relative w-full overflow-hidden rounded-3xl bg-gradient-to-br ${currentTheme.gradient} p-6 shadow-lg backdrop-blur-xs sm:w-screen sm:max-w-md`}
    >
      {/* Decorative background elements */}
      <div className="pointer-events-none absolute -top-16 -right-16 h-48 w-48 rounded-full bg-white/5" />
      <div className="pointer-events-none absolute -bottom-12 -left-12 h-40 w-40 rounded-full bg-white/5" />

      {/* Header */}
      <div className="relative mb-4 flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-white/20 p-3 backdrop-blur-sm">
            {success ? (
              is_open ? (
                <DoorOpen className="h-8 w-8 text-white" strokeWidth={2} />
              ) : (
                <DoorClosed className="h-8 w-8 text-white" strokeWidth={2} />
              )
            ) : (
              <XCircle className="h-8 w-8 text-white" strokeWidth={2} />
            )}
          </div>
          <div>
            <h3 className="text-2xl font-bold text-white">
              {success
                ? is_open
                  ? "Door Opened"
                  : "Door Closed"
                : "Operation Failed"}
            </h3>
            <p className="mt-0.5 text-sm text-white/80 capitalize">
              {action} operation {success ? "completed" : "failed"}
            </p>
          </div>
        </div>
        {success ? (
          <div className="rounded-full bg-white/20 p-2 backdrop-blur-sm">
            <CheckCircle2 className="h-5 w-5 text-white" strokeWidth={2.5} />
          </div>
        ) : (
          <div className="rounded-full bg-white/20 p-2 backdrop-blur-sm">
            <AlertCircle className="h-5 w-5 text-white" strokeWidth={2.5} />
          </div>
        )}
      </div>

      {/* API Status Badge */}
      <div className="relative mb-4 flex items-center gap-2">
        <Chip
          size="sm"
          variant="flat"
          className="bg-white/20 text-white backdrop-blur-sm"
          startContent={<Server className="h-3 w-3" />}
        >
          HTTP {statusCode}
        </Chip>
        <Chip
          size="sm"
          variant="flat"
          className={`${currentTheme.statusBg} text-white backdrop-blur-sm`}
          startContent={
            success ? (
              <CheckCircle2 className="h-3 w-3" />
            ) : (
              <XCircle className="h-3 w-3" />
            )
          }
        >
          {statusText}
        </Chip>
        <Chip
          size="sm"
          variant="flat"
          className="bg-white/20 text-white backdrop-blur-sm"
          startContent={<Activity className="h-3 w-3" />}
        >
          {action.toUpperCase()}
        </Chip>
      </div>

      {/* Status Message */}
      <div className="relative mb-4 rounded-2xl bg-white/15 p-4 backdrop-blur-sm">
        <div className="flex items-start gap-2">
          <Radio className="mt-0.5 h-4 w-4 text-white/80" strokeWidth={2} />
          <p className="flex-1 text-sm font-medium text-white">{message}</p>
        </div>
      </div>

      {/* Door Status Card */}
      <div className="relative mb-3 rounded-2xl bg-black/20 p-4 backdrop-blur-sm">
        <div className="mb-3 flex items-center justify-between">
          <span className="flex items-center gap-2 text-sm font-medium text-white/90">
            <Zap className="h-4 w-4" strokeWidth={2} />
            Current Status
          </span>
          <div
            className={`flex items-center gap-2 rounded-full px-3 py-1.5 ${currentTheme.statusBg} backdrop-blur-sm`}
          >
            {is_open ? (
              <LockOpen className="h-4 w-4 text-white" strokeWidth={2} />
            ) : (
              <Lock className="h-4 w-4 text-white" strokeWidth={2} />
            )}
            <span className="text-sm font-semibold text-white">
              {is_open ? "Open" : "Closed"}
            </span>
          </div>
        </div>

        {/* Info Grid */}
        <div className="grid grid-cols-2 gap-3">
          {timestamp && (
            <div className="flex items-center gap-2 rounded-xl bg-white/10 p-3">
              <Clock className="h-4 w-4 text-white/70" strokeWidth={2} />
              <div className="flex-1">
                <p className="text-xs text-white/60">Time</p>
                <p className="text-sm font-medium text-white">
                  {formatTime(timestamp)}
                </p>
              </div>
            </div>
          )}

          <div className="flex items-center gap-2 rounded-xl bg-white/10 p-3">
            <ShieldCheck className="h-4 w-4 text-white/70" strokeWidth={2} />
            <div className="flex-1">
              <p className="text-xs text-white/60">Security</p>
              <p className="text-sm font-medium text-white">
                {success ? "Verified" : "Failed"}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Additional Details */}
      {details && (
        <div className="relative space-y-2 rounded-xl bg-black/15 p-3 backdrop-blur-sm">
          <p className="text-xs font-medium text-white/90">Response Details</p>
          {Object.entries(details).map(([key, value]) => (
            <div key={key} className="flex items-center justify-between">
              <span className="text-xs text-white/60 capitalize">
                {key.replace(/_/g, " ")}:
              </span>
              <span className="text-xs font-medium text-white">
                {typeof value === "string" || typeof value === "number"
                  ? String(value)
                  : JSON.stringify(value)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Timestamp Footer */}
      {timestamp && (
        <div className="relative mt-3 rounded-xl bg-black/10 px-3 py-2 backdrop-blur-sm">
          <p className="text-center text-xs text-white/60">
            Operation timestamp: {formatFullTime(timestamp)}
          </p>
        </div>
      )}

      {/* Visual indicator - animated pulse for active state */}
      {success && (
        <div className="absolute right-4 bottom-4">
          <div className="relative flex h-3 w-3">
            <span
              className={`absolute inline-flex h-full w-full animate-ping rounded-full ${currentTheme.pulseColor} opacity-75`}
            ></span>
            <span
              className={`relative inline-flex h-3 w-3 rounded-full ${currentTheme.ringColor}`}
            ></span>
          </div>
        </div>
      )}
    </div>
  );
}
