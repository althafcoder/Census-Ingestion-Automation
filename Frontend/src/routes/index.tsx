import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import {
  BookOpen,
  Download,
  Home,
  RefreshCw,
  Sparkles,
  ChevronRight,
  Loader2,
  Search,
  CheckCircle2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FileDropzone } from "@/components/renewal/FileDropzone";
import { PipelineSteps, type PipelineStep } from "@/components/renewal/PipelineSteps";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Census Ingestion Automation" },
      {
        name: "description",
        content:
          "Automated matching of employee census rosters with carrier benefit rates.",
      },
      { property: "og:title", content: "Census Ingestion Automation" },
      {
        property: "og:description",
        content:
          "Upload census and invoice files to auto-generate a filled census.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: IngestionPage,
});

interface HistoryEntry {
  id: string;
  censusName: string;
  invoiceName: string;
  timestamp: string;
  downloadUrl: string;
}

interface IngestionResult {
  downloadUrl: string;
  filename: string;
  summary: { label: string; value: string }[];
}

const INITIAL_STEPS: PipelineStep[] = [
  {
    title: "Census Ingestion",
    description: "Ingesting current employee census",
    status: "idle",
  },
  {
    title: "Invoice Ingestion",
    description: "Extracting rates via LLM/OCR",
    status: "idle",
  },
  {
    title: "Data Matching",
    description: "Cross-referencing members to plans & tiers",
    status: "idle",
  },
  {
    title: "Summary",
    description: "Generating updated census roster",
    status: "idle",
  },
];

function IngestionPage() {
  const [census, setCensus] = useState<File | null>(null);
  const [invoice, setInvoice] = useState<File | null>(null);
  const [processing, setProcessing] = useState(false);
  const [steps, setSteps] = useState<PipelineStep[]>(INITIAL_STEPS);
  const [result, setResult] = useState<IngestionResult | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const canProcess = Boolean(census && invoice) && !processing;

  const statusMessage = useMemo(() => {
    if (processing) return "Processing…";
    if (census && invoice) return "Both files ready. Click Process to begin.";
    return "Upload both files to enable processing.";
  }, [census, invoice, processing]);

  const advanceStep = (idx: number) =>
    new Promise<void>((resolve) => {
      setSteps((prev) =>
        prev.map((s, i) =>
          i < idx ? { ...s, status: "done" } : i === idx ? { ...s, status: "active" } : s,
        ),
      );
      setTimeout(resolve, 600);
    });

  const handleProcess = async () => {
    if (!census || !invoice) return;
    setProcessing(true);
    setError(null);
    setResult(null);
    setSteps(INITIAL_STEPS);

    try {
      // Animate through pipeline steps while the backend processes.
      const stepPromise = (async () => {
        for (let i = 0; i < INITIAL_STEPS.length; i++) {
          await advanceStep(i);
        }
      })();

      // TODO: Wire to your backend. Expected response:
      // { downloadUrl: string, filename?: string, summary?: {label,value}[] }
      const apiBase = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
      let apiResult: IngestionResult | null = null;

      if (apiBase) {
        const formData = new FormData();
        formData.append("census", census);
        formData.append("invoice", invoice);
        const res = await fetch(`${apiBase}/process`, {
          method: "POST",
          body: formData,
        });
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        const contentType = res.headers.get("content-type") ?? "";
        if (contentType.includes("application/json")) {
          const data = (await res.json()) as Partial<IngestionResult>;
          apiResult = {
            downloadUrl: data.downloadUrl ?? "",
            filename: data.filename ?? `ingested-census-${Date.now()}.xlsx`,
            summary: data.summary ?? [],
          };
        } else {
          const blob = await res.blob();
          apiResult = {
            downloadUrl: URL.createObjectURL(blob),
            filename: `ingested-census-${Date.now()}.xlsx`,
            summary: [],
          };
        }
      } else {
        // Demo fallback so the UI is fully interactive with no backend.
        await new Promise((r) => setTimeout(r, 1200));
        apiResult = {
          downloadUrl: "#",
          filename: `filled-census-${Date.now()}.xlsx`,
          summary: [
            { label: "Members matched", value: "128" },
            { label: "Plans", value: "6" },
            { label: "Tiers", value: "4" },
          ],
        };
      }

      await stepPromise;
      setSteps((prev) => prev.map((s) => ({ ...s, status: "done" })));
      setResult(apiResult);
      setHistory((prev) => [
        {
          id: typeof crypto !== "undefined" && typeof crypto.randomUUID === "function" 
                ? crypto.randomUUID() 
                : Math.random().toString(36).substring(2, 15),
          censusName: census.name,
          invoiceName: invoice.name,
          timestamp: new Date().toLocaleString(),
          downloadUrl: apiResult!.downloadUrl,
        },
        ...prev,
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Processing failed");
      setSteps(INITIAL_STEPS);
    } finally {
      setProcessing(false);
    }
  };

  const handleDownload = () => {
    if (!result) return;
    const a = document.createElement("a");
    a.href = result.downloadUrl;
    a.download = result.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Top search bar */}
      <div className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-7xl items-center px-6 py-3">
          <div className="relative mx-auto w-full max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search files, categories, reports…"
              className="w-full rounded-md border border-border bg-background py-2 pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
            />
          </div>
        </div>
      </div>

      <main className="mx-auto max-w-7xl px-6 py-8">
        {/* Breadcrumb */}
        <nav className="mb-4 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Home className="h-3.5 w-3.5" />
          <span>Home</span>
          <ChevronRight className="h-3.5 w-3.5" />
          <span className="text-foreground">Census Ingestion Automation</span>
        </nav>

        {/* Header */}
        <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div className="flex gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <RefreshCw className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-foreground">
                Census Ingestion Automation
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Automated matching of employee census rosters with carrier benefit rates.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-success/30 bg-success/10 px-3 py-1.5 text-xs font-medium text-success-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-success" />
              Engine: Ingestion v2 Active
            </span>
            <Button variant="outline" size="sm">
              <BookOpen className="mr-1.5 h-4 w-4" /> Docs
            </Button>
          </div>
        </div>

        {/* Upload cards */}
        <div className="grid gap-5 md:grid-cols-2">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">1. Census File</CardTitle>
              <p className="text-xs text-muted-foreground">
                Upload the current employee census roster.
              </p>
            </CardHeader>
            <CardContent>
              <FileDropzone
                file={census}
                onFileChange={setCensus}
                accept=".csv,.xlsx,.xls,.pdf"
                acceptLabel="CSV, Excel & PDF"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">2. Invoice</CardTitle>
              <p className="text-xs text-muted-foreground">
                Upload the invoice issued by the carrier.
              </p>
            </CardHeader>
            <CardContent>
              <FileDropzone
                file={invoice}
                onFileChange={setInvoice}
                accept=".pdf,.doc,.docx,.png,.jpg,.jpeg"
                acceptLabel="PDF, Word & Images"
              />
            </CardContent>
          </Card>
        </div>

        {/* Action bar */}
        <Card className="mt-5">
          <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
            <p className="text-sm text-muted-foreground">{statusMessage}</p>
            <Button onClick={handleProcess} disabled={!canProcess}>
              {processing ? (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-1.5 h-4 w-4" />
              )}
              Process
            </Button>
          </CardContent>
        </Card>

        {error && (
          <div className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Results row */}
        <div className="mt-6 grid gap-5 lg:grid-cols-3">
          <div className="space-y-5 lg:col-span-2">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Results</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Structured summary ready for review and export.
                </p>
              </CardHeader>
              <CardContent>
                {result ? (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-success-foreground">
                      <CheckCircle2 className="h-4 w-4 text-success" />
                      Census generated successfully.
                    </div>
                    {result.summary.length > 0 && (
                      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                        {result.summary.map((s) => (
                          <div
                            key={s.label}
                            className="rounded-md border border-border bg-muted/30 p-3"
                          >
                            <p className="text-xs text-muted-foreground">{s.label}</p>
                            <p className="mt-1 text-lg font-semibold text-foreground">
                              {s.value}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                    <Button onClick={handleDownload} className="w-full sm:w-auto">
                      <Download className="mr-1.5 h-4 w-4" /> Download Filled Census
                    </Button>
                  </div>
                ) : (
                  <div className="flex min-h-32 items-center justify-center text-center text-sm text-muted-foreground">
                    No results available. Upload census and invoice files above to start.
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Processing History</CardTitle>
                <p className="text-xs text-muted-foreground">Recent runs in system.</p>
              </CardHeader>
              <CardContent>
                {history.length === 0 ? (
                  <div className="flex min-h-24 items-center justify-center text-sm text-muted-foreground">
                    No past runs recorded.
                  </div>
                ) : (
                  <ul className="divide-y divide-border">
                    {history.map((h) => (
                      <li key={h.id} className="flex items-center justify-between gap-4 py-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-foreground">
                            {h.censusName}
                          </p>
                          <p className="truncate text-xs text-muted-foreground">
                            {h.invoiceName} · {h.timestamp}
                          </p>
                        </div>
                        <a
                          href={h.downloadUrl}
                          download
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                        >
                          <Download className="h-3.5 w-3.5" /> Download
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          <Card className="h-fit">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Pipeline</CardTitle>
              <p className="text-xs text-muted-foreground">Live progress.</p>
            </CardHeader>
            <CardContent>
              <PipelineSteps steps={steps} />
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}
