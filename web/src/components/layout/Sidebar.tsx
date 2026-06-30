import { Link, NavLink } from "react-router-dom";
import { Radar, LayoutList, LineChart, History, Settings as Cog, LogOut, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

const NAV: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: "/", label: "Findings", icon: LayoutList, end: true },
  { to: "/monitoring", label: "Monitoring", icon: LineChart },
  { to: "/investigations", label: "Investigations", icon: History },
  { to: "/settings", label: "Connections", icon: Cog },
];

export function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface px-3 py-4 md:flex">
      <div className="mb-6 flex items-center gap-2 px-2">
        <div className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-white">
          <Radar size={18} strokeWidth={2.5} />
        </div>
        <div>
          <p className="text-sm font-bold leading-none">Scout</p>
          <p className="mt-0.5 text-[11px] text-muted">autonomous analyst</p>
        </div>
      </div>

      <nav className="flex flex-col gap-1">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-elevated text-fg"
                  : "text-muted hover:bg-elevated/60 hover:text-fg",
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon size={18} className={isActive ? "text-primary" : ""} />
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto flex flex-col gap-2">
        <div className="rounded-xl border border-border bg-elevated/50 p-3">
          <p className="text-[11px] font-medium text-muted">Monitoring</p>
          <p className="mt-1 text-[13px] font-semibold text-healthy">● Live</p>
          <p className="mt-0.5 text-[11px] text-muted">Scanning every weekday baseline</p>
        </div>
        <Link
          to="/signin"
          className="flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-muted transition-colors hover:bg-elevated/60 hover:text-fg"
        >
          <LogOut size={18} /> Sign out
        </Link>
      </div>
    </aside>
  );
}
