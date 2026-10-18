"use client";

import { useState } from "react";
import useSWR from "swr";
import { Search, ChevronLeft, ChevronRight, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useWorkspace } from "@/lib/workspace";

type Kind = "jobs" | "applicants";
type Catalog = {
  total: number;
  next_offset: number | null;
  items: {
    id: string;
    title: string;
    summary: string;
    skills: string[];
    region: string;
    state: string;
  }[];
};

export function SampleCatalog({
  initialKind = "jobs",
}: {
  initialKind?: Kind;
}) {
  const { data: workspace } = useWorkspace();
  const [kind, setKind] = useState<Kind>(initialKind);
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const enabled = workspace.context.mode === "sample";
  const params = new URLSearchParams({
    kind,
    q: query,
    offset: String(offset),
  });
  const { data, error, isLoading } = useSWR<Catalog>(
    enabled ? "/api/demo/catalog?" + params : null,
    async (url: string) => {
      const response = await fetch(url, { cache: "no-store" });
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          result?.error?.message || "The sample market could not be loaded.",
        );
      return result.data;
    },
    { keepPreviousData: false, errorRetryCount: 0 },
  );
  if (!enabled) return null;

  return (
    <section
      id="sample-market"
      aria-labelledby="sample-market-title"
      className="mx-auto mt-12 w-full max-w-6xl border-t pt-10"
    >
      <div className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="eyebrow">Explore the sample market</p>
          <h2 id="sample-market-title" className="mt-2 font-serif text-3xl">
            A full house, ready to explore.
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Browse the fictional profiles and jobs behind this demo. Your
            matching suggestions appear in the usual workspace, with the same
            attention limits and separate decisions from both sides.
          </p>
        </div>
        <div
          role="group"
          aria-label="Sample market records"
          className="flex gap-1 rounded-md border p-1"
        >
          {(["jobs", "applicants"] as const).map((value) => (
            <Button
              key={value}
              size="sm"
              variant={kind === value ? "default" : "ghost"}
              aria-pressed={kind === value}
              onClick={() => {
                setKind(value);
                setOffset(0);
              }}
            >
              {value === "jobs" ? "Jobs" : "Applicants"}
            </Button>
          ))}
        </div>
      </div>
      <form
        className="my-6 flex max-w-xl gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(input.trim());
          setOffset(0);
        }}
      >
        <Input
          aria-label="Search the sample market"
          placeholder={`Search sample ${kind}…`}
          value={input}
          maxLength={100}
          onChange={(event) => setInput(event.target.value)}
        />
        <Button type="submit" variant="outline">
          <Search aria-hidden="true" />
          Search
        </Button>
      </form>
      <div aria-live="polite" className="mb-4 text-sm text-muted-foreground">
        {isLoading ? (
          <span className="flex items-center gap-2">
            <LoaderCircle className="size-4 animate-spin" />
            Loading sample {kind}…
          </span>
        ) : error ? (
          <span role="alert">{error.message}</span>
        ) : data ? (
          `${data.total.toLocaleString("en-US")} sample ${kind}${query ? ` matching “${query}”` : ""}`
        ) : null}
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data?.items.map((record) => (
          <details key={record.id} className="panel min-w-0 p-5">
            <summary className="cursor-pointer list-none">
              <Badge variant="outline" className="mb-3">
                Synthetic {kind === "jobs" ? "job" : "applicant"}
              </Badge>
              <h3 className="font-serif text-xl leading-tight">
                {record.title.replace(/^\[SYNTHETIC \d+\]\s*/, "")}
              </h3>
              <p className="mt-2 text-xs text-muted-foreground">
                {record.region} · {record.state.toLowerCase()} · View details
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {record.skills.slice(0, 5).map((skill) => (
                  <Badge key={skill} variant="secondary">
                    {skill}
                  </Badge>
                ))}
              </div>
            </summary>
            <p className="mt-4 border-t pt-4 text-sm whitespace-pre-line text-muted-foreground">
              {record.summary}
            </p>
          </details>
        ))}
      </div>
      {data && data.items.length === 0 && (
        <p className="rounded-md border p-6 text-sm text-muted-foreground">
          No sample {kind} match this search.
        </p>
      )}
      <div className="mt-6 flex items-center justify-between gap-3">
        <Button
          variant="outline"
          disabled={offset === 0 || isLoading}
          onClick={() => setOffset(Math.max(0, offset - 24))}
        >
          <ChevronLeft aria-hidden="true" />
          Previous
        </Button>
        <span className="text-xs text-muted-foreground">
          {data && data.total > 0
            ? `${offset + 1}–${offset + data.items.length} of ${data.total.toLocaleString("en-US")}`
            : ""}
        </span>
        <Button
          variant="outline"
          disabled={data?.next_offset == null || isLoading}
          onClick={() =>
            data?.next_offset != null && setOffset(data.next_offset)
          }
        >
          Next
          <ChevronRight aria-hidden="true" />
        </Button>
      </div>
    </section>
  );
}
