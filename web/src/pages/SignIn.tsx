import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Radar, ArrowRight, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ThemeToggle } from "@/components/ui/ThemeToggle";

const inputCls =
  "h-10 w-full rounded-xl border border-border bg-elevated px-3 text-sm text-fg outline-none focus:border-primary";

export function SignIn() {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    // Demo: no real auth in v1 — continue to the app.
    setTimeout(() => nav("/"), 500);
  };

  return (
    <div className="relative grid min-h-screen place-items-center bg-bg px-4">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0, transition: { duration: 0.3, ease: "easeOut" } }}
        className="w-full max-w-sm"
      >
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-primary text-white shadow-lift">
            <Radar size={26} strokeWidth={2.4} />
          </div>
          <h1 className="text-xl font-bold tracking-tight">Welcome to Scout</h1>
          <p className="mt-1 text-sm text-muted">Your autonomous data analyst for Shopify.</p>
        </div>

        <Card className="p-6">
          <form onSubmit={submit} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium">Email</span>
              <input className={inputCls} type="email" placeholder="you@store.com" autoComplete="email" required />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium">Password</span>
              <input className={inputCls} type="password" placeholder="••••••••" autoComplete="current-password" required />
            </label>
            <Button type="submit" variant="primary" className="mt-1 w-full" disabled={busy}>
              {busy ? <Loader2 size={16} className="animate-spin" /> : <>Continue <ArrowRight size={16} /></>}
            </Button>
          </form>
          <button
            onClick={() => nav("/")}
            className="mt-3 w-full text-center text-[13px] text-muted transition-colors hover:text-fg"
          >
            Continue with the demo store →
          </button>
        </Card>

        <p className="mt-4 text-center text-[11px] text-muted">
          v1 demo — authentication is not yet wired. Any input continues to the dashboard.
        </p>
      </motion.div>
    </div>
  );
}
