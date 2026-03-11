import { ArrowRight02Icon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

export default function FeatureDigestCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        {getToolCategoryIcon("linear", {
          width: 14,
          height: 14,
          showBackground: false,
        })}
        <span className="text-sm font-medium text-zinc-100">
          Feature Digest — this week
        </span>
        <span className="flex items-center gap-1 text-[11px] text-zinc-500">
          11 requests <ArrowRight02Icon width={10} height={10} /> 4 themes
        </span>
      </div>

      <div className="rounded-xl bg-zinc-900 p-3 space-y-0.5">
        {/* Group 1: API & Integrations */}
        <div className="pb-2.5">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="text-xs font-medium text-zinc-300">
              API &amp; Integrations (5 requests)
            </span>
            <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-400">
              High Volume
            </span>
          </div>
          <p className="text-xs text-zinc-400">
            &quot;REST API access&quot; × 3 · &quot;Zapier integration&quot; × 2
          </p>
          <p className="flex items-center gap-1 text-xs text-primary">
            <ArrowRight02Icon width={11} height={11} />
            ENG-461 created
          </p>
        </div>

        {/* Group 2: Mobile Experience */}
        <div className="border-t border-zinc-800 pt-2.5 pb-2.5">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="text-xs font-medium text-zinc-300">
              Mobile Experience (3 requests)
            </span>
          </div>
          <p className="text-xs text-zinc-400">
            &quot;iOS app&quot; × 2 · &quot;offline mode&quot; × 1
          </p>
          <p className="flex items-center gap-1 text-xs text-zinc-500">
            <ArrowRight02Icon width={11} height={11} />
            ENG-462 created (roadmap Q3)
          </p>
        </div>

        {/* Group 3: Reporting & Export */}
        <div className="border-t border-zinc-800 pt-2.5 pb-2.5">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="text-xs font-medium text-zinc-300">
              Reporting &amp; Export (2 requests)
            </span>
          </div>
          <p className="text-xs text-zinc-400">
            &quot;CSV export&quot; × 1 · &quot;custom dashboards&quot; × 1
          </p>
          <p className="flex items-center gap-1 text-xs text-zinc-500">
            <ArrowRight02Icon width={11} height={11} />
            ENG-463 created
          </p>
        </div>

        {/* Group 4: SSO / Enterprise Auth */}
        <div className="border-t border-zinc-800 pt-2.5">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="text-xs font-medium text-zinc-300">
              SSO / Enterprise Auth (1 request)
            </span>
            <span className="rounded-full bg-red-500/15 px-1.5 py-0.5 text-[10px] text-red-400">
              High Priority
            </span>
          </div>
          <p className="text-xs text-zinc-400">
            &quot;SAML SSO&quot; — from enterprise prospect
          </p>
          <p className="flex items-center gap-1 text-xs text-primary">
            <ArrowRight02Icon width={11} height={11} />
            ENG-464 created
          </p>
        </div>
      </div>
    </div>
  );
}
