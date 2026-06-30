import type { Finding, InventoryLevel, InvestigationRun, RevenuePoint } from "./types";
import { mockFindings, mockInventory, mockRevenue, mockRuns } from "./mock";

const env = import.meta.env as Record<string, string | undefined>;
export const API_URL = env.VITE_API_URL || "http://localhost:8000";
export const STORE_ID = env.VITE_STORE_ID || "cortexium-sim";

export type Source = "live" | "mock";
export interface Result<T> {
  data: T;
  source: Source;
}

async function tryFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 4000);
  try {
    const res = await fetch(`${API_URL}${path}`, { ...init, signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(t);
  }
}

function deriveSpark(baseline: number, observed: number): number[] {
  const arr = Array.from({ length: 11 }, (_, i) => Math.round(baseline * (0.96 + 0.012 * Math.sin(i))));
  arr.push(Math.round(observed));
  return arr;
}

function mapFinding(row: any): Finding {
  const f = row.finding ?? row;
  const a = f.anomaly ?? {};
  return {
    id: row.id ?? f.id ?? 0,
    store_id: f.store_id ?? row.store_id ?? STORE_ID,
    headline: f.headline ?? row.headline ?? "",
    confirmed_cause: f.confirmed_cause ?? row.confirmed_cause ?? null,
    confidence: f.confidence ?? row.confidence ?? 0,
    recommended_action: f.recommended_action ?? "",
    created_at: row.created_at ?? f.created_at ?? new Date().toISOString(),
    llm_mode: f.llm_mode ?? "stub",
    inconclusive: f.inconclusive ?? false,
    evidence: f.evidence ?? [],
    investigated: f.investigated ?? [],
    anomaly: a,
    spark: deriveSpark(a.baseline ?? 1000, a.observed_value ?? 1000),
  };
}

export async function getFindings(): Promise<Result<Finding[]>> {
  try {
    const json = await tryFetch<{ findings: any[] }>(
      `/findings?store_id=${encodeURIComponent(STORE_ID)}&limit=50`,
    );
    const data = (json.findings ?? []).map(mapFinding);
    return { data: data.length ? data : mockFindings, source: data.length ? "live" : "mock" };
  } catch {
    return { data: mockFindings, source: "mock" };
  }
}

export async function getRevenue(): Promise<Result<RevenuePoint[]>> {
  try {
    const json = await tryFetch<{ series: any[]; baseline: any[] }>(
      `/metrics/revenue?store_id=${encodeURIComponent(STORE_ID)}`,
    );
    const baseByDate = new Map((json.baseline ?? []).map((b) => [b.date, b.baseline]));
    const data: RevenuePoint[] = (json.series ?? []).map((p) => ({
      date: p.date,
      value: p.value,
      weekday: p.weekday,
      baseline: baseByDate.get(p.date) ?? null,
    }));
    return data.length ? { data, source: "live" } : { data: mockRevenue(), source: "mock" };
  } catch {
    return { data: mockRevenue(), source: "mock" };
  }
}

export async function getInventory(): Promise<Result<InventoryLevel[]>> {
  try {
    const json = await tryFetch<{ levels: any[] }>(
      `/metrics/inventory?store_id=${encodeURIComponent(STORE_ID)}`,
    );
    const data: InventoryLevel[] = (json.levels ?? []).map((l) => ({
      sku: l.sku,
      title: l.title ?? l.sku,
      available: l.available ?? 0,
      daysLeft: l.available === 0 ? 0 : null,
    }));
    return data.length ? { data, source: "live" } : { data: mockInventory, source: "mock" };
  } catch {
    return { data: mockInventory, source: "mock" };
  }
}

export async function getInvestigations(): Promise<Result<InvestigationRun[]>> {
  try {
    const json = await tryFetch<{ runs: any[] }>(
      `/investigations?store_id=${encodeURIComponent(STORE_ID)}&limit=50`,
    );
    const data: InvestigationRun[] = (json.runs ?? []).map((r) => ({
      id: r.id,
      trigger: r.trigger,
      status: r.status,
      startedAt: r.startedAt,
      durationMs: r.durationMs ?? 0,
      store_id: r.store_id ?? STORE_ID,
      outcome: r.outcome ?? "",
      findingId: r.findingId ?? null,
    }));
    return data.length ? { data, source: "live" } : { data: mockRuns, source: "mock" };
  } catch {
    return { data: mockRuns, source: "mock" };
  }
}

export async function runScout(): Promise<{ status: string; source: Source }> {
  try {
    const json = await tryFetch<{ status: string }>(`/scout/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ store_id: STORE_ID, force: true }),
    });
    return { status: json.status ?? "queued", source: "live" };
  } catch {
    return { status: "queued (demo)", source: "mock" };
  }
}
