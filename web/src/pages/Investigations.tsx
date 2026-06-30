import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowUpDown, Webhook, Clock, MousePointerClick, ChevronRight, History } from "lucide-react";
import { getInvestigations } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import type { InvestigationRun, Severity } from "@/lib/types";
import { relativeTime } from "@/lib/format";
import { Card } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPill } from "@/components/ui/StatusPill";

const STATUS_SEV: Record<InvestigationRun["status"], { sev: Severity; label: string }> = {
  completed: { sev: "healthy", label: "Completed" },
  running: { sev: "info", label: "Running" },
  failed: { sev: "critical", label: "Failed" },
  inconclusive: { sev: "warning", label: "Inconclusive" },
};

const TRIGGER_ICON = { webhook: Webhook, schedule: Clock, manual: MousePointerClick };

type SortKey = "startedAt" | "durationMs" | "status";

export function Investigations() {
  const nav = useNavigate();
  const { data: runs, loading } = useResource(getInvestigations);
  const [key, setKey] = useState<SortKey>("startedAt");
  const [asc, setAsc] = useState(false);

  const rows = useMemo(() => {
    return [...(runs ?? [])].sort((a, b) => {
      let cmp = 0;
      if (key === "startedAt") cmp = new Date(a.startedAt).getTime() - new Date(b.startedAt).getTime();
      else if (key === "durationMs") cmp = a.durationMs - b.durationMs;
      else cmp = a.status.localeCompare(b.status);
      return asc ? cmp : -cmp;
    });
  }, [runs, key, asc]);

  const sortBtn = (k: SortKey, label: string) => (
    <button
      onClick={() => (k === key ? setAsc((v) => !v) : (setKey(k), setAsc(false)))}
      className="inline-flex items-center gap-1 hover:text-fg"
    >
      {label} <ArrowUpDown size={12} className={key === k ? "text-primary" : "opacity-40"} />
    </button>
  );

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Investigations</h1>
        <p className="mt-0.5 text-sm text-muted">Every run — manual, scheduled, and webhook-triggered.</p>
      </div>

      {loading ? (
        <Card className="p-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="mt-2 h-8 w-full" />
          <Skeleton className="mt-2 h-8 w-full" />
        </Card>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={History}
          title="No runs yet"
          body="Investigation runs appear here as they fire — manual, scheduled, and webhook-triggered. Trigger one from the top bar."
        />
      ) : (
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs font-medium text-muted">
                <th className="px-4 py-3">Run</th>
                <th className="px-4 py-3">Trigger</th>
                <th className="px-4 py-3">{sortBtn("status", "Status")}</th>
                <th className="px-4 py-3">{sortBtn("startedAt", "Started")}</th>
                <th className="px-4 py-3">{sortBtn("durationMs", "Duration")}</th>
                <th className="px-4 py-3">Outcome</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const s = STATUS_SEV[r.status];
                const TIcon = TRIGGER_ICON[r.trigger];
                const clickable = r.findingId != null;
                return (
                  <tr
                    key={r.id}
                    onClick={() => clickable && nav(`/findings/${r.findingId}`)}
                    onKeyDown={(e) => clickable && e.key === "Enter" && nav(`/findings/${r.findingId}`)}
                    tabIndex={clickable ? 0 : -1}
                    role={clickable ? "button" : undefined}
                    className={`border-b border-border/70 last:border-0 ${
                      clickable ? "cursor-pointer transition-colors hover:bg-elevated/50" : ""
                    }`}
                  >
                    <td className="px-4 py-3 font-mono text-[12px] text-muted">{r.id}</td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1.5 text-[13px] capitalize text-muted">
                        <TIcon size={14} /> {r.trigger}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusPill severity={s.sev} label={s.label} />
                    </td>
                    <td className="px-4 py-3 text-muted">{relativeTime(r.startedAt)}</td>
                    <td className="tnum px-4 py-3 text-muted">{(r.durationMs / 1000).toFixed(1)}s</td>
                    <td className="px-4 py-3">{r.outcome}</td>
                    <td className="px-4 py-3 text-right">
                      {clickable && <ChevronRight size={16} className="text-muted" />}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
      )}
    </div>
  );
}
