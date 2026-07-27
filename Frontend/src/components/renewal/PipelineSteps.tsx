import { Check, Loader2 } from "lucide-react";

export type StepStatus = "idle" | "active" | "done";

export interface PipelineStep {
  title: string;
  description: string;
  status: StepStatus;
}

export function PipelineSteps({ steps }: { steps: PipelineStep[] }) {
  return (
    <ol className="space-y-4">
      {steps.map((step, idx) => (
        <li key={step.title} className="flex gap-3">
          <div
            className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-medium transition-colors ${
              step.status === "done"
                ? "bg-success/15 text-success-foreground"
                : step.status === "active"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground"
            }`}
          >
            {step.status === "done" ? (
              <Check className="h-3.5 w-3.5" />
            ) : step.status === "active" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              idx + 1
            )}
          </div>
          <div className="min-w-0">
            <p
              className={`text-sm font-medium ${
                step.status === "idle" ? "text-muted-foreground" : "text-foreground"
              }`}
            >
              {step.title}
            </p>
            <p className="text-xs text-muted-foreground">{step.description}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
