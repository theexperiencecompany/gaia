import { Card, CardBody, CardHeader } from "@heroui/card";

import { Skeleton } from "@/components/ui/shadcn/skeleton";
import { StarsIcon } from '@/icons';

export default function WorkflowLoadingState() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <StarsIcon className="h-5 w-5 animate-pulse text-blue-400" />
        <h3 className="text-lg font-semibold text-zinc-100">Workflow</h3>
      </div>
      <Card className="border-zinc-700 bg-zinc-800">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-4 bg-zinc-600" />
            <Skeleton className="h-5 w-48 bg-zinc-600" />
          </div>
        </CardHeader>
        <CardBody className="pt-0">
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-start gap-3">
                <Skeleton className="mt-1 h-6 w-6 rounded-full bg-zinc-600" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-40 bg-zinc-600" />
                  <Skeleton className="h-3 w-32 bg-zinc-600" />
                </div>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>
      <div className="animate-pulse text-sm text-zinc-400">
        ✨ Generating workflow plan for your todo...
      </div>
    </div>
  );
}
