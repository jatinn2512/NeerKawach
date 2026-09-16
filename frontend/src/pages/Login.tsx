import { RouteLink, useNavigate } from "@/utils/router";
import { Lock, ShieldCheck, User, Waves } from "lucide-react";
import { useState, type FormEvent } from "react";
import { REGION } from "@/data/pilot";
import { useSim } from "@/state/simulation";

export function LoginPage() {
  const sim = useSim();
  const navigate = useNavigate();
  const [operator, setOperator] = useState("OPR-KA-0142");
  const [password, setPassword] = useState("");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    sim.signIn("R. Nandakumar");
    void navigate("/dashboard");
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden flex-col justify-between border-r border-border bg-sidebar p-12 lg:flex">
        <div className="flex items-center gap-3">
          <span className="flex size-11 items-center justify-center rounded-md bg-primary/15 text-primary">
            <Waves className="size-6" />
          </span>
          <div>
            <p className="text-lg font-semibold tracking-tight">FloodOps</p>
            <p className="text-[11px] tracking-[0.16em] text-muted-foreground uppercase">
              Flood Decision Support System
            </p>
          </div>
        </div>

        <div className="max-w-lg">
          <h1 className="text-3xl leading-tight font-semibold tracking-tight">
            Rainfall-driven flood simulation and decision support for disaster
            management operations.
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
            Run storm scenarios over preconfigured catchments, visualise flood
            depth progression, identify critical infrastructure at risk and
            plan lower-risk access routes — from a single operational console.
          </p>
          <dl className="mt-8 grid grid-cols-3 gap-4 border-t border-border pt-6 text-sm">
            <div>
              <dt className="text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                Pilot catchment
              </dt>
              <dd className="mt-1 font-medium">{REGION.area}</dd>
            </div>
            <div>
              <dt className="text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                Coverage
              </dt>
              <dd className="mt-1 font-medium tabular">{REGION.coverageKm2} km²</dd>
            </div>
            <div>
              <dt className="text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                Reference system
              </dt>
              <dd className="mt-1 font-medium">{REGION.crs}</dd>
            </div>
          </dl>
        </div>

        <p className="text-[11px] text-muted-foreground">
          Restricted system. Authorised disaster-management personnel only. All
          activity is logged.
        </p>
      </div>

      <div className="flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="flex size-10 items-center justify-center rounded-md bg-primary/15 text-primary">
              <Waves className="size-5" />
            </span>
            <p className="text-lg font-semibold">FloodOps</p>
          </div>

          <h2 className="text-xl font-semibold tracking-tight">Operator sign in</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Use your government-issued operator credentials.
          </p>

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <label className="block">
              <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                Operator ID / Email
              </span>
              <div className="mt-1.5 flex items-center gap-2 rounded-md border border-input bg-card px-3">
                <User className="size-4 text-muted-foreground" />
                <input
                  value={operator}
                  onChange={(e) => setOperator(e.target.value)}
                  required
                  maxLength={80}
                  className="w-full bg-transparent py-2.5 text-sm outline-none"
                />
              </div>
            </label>

            <label className="block">
              <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                Password
              </span>
              <div className="mt-1.5 flex items-center gap-2 rounded-md border border-input bg-card px-3">
                <Lock className="size-4 text-muted-foreground" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  maxLength={128}
                  placeholder="••••••••"
                  className="w-full bg-transparent py-2.5 text-sm outline-none"
                />
              </div>
            </label>

            <button
              type="submit"
              className="w-full rounded-md bg-primary py-2.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
            >
              Sign In
            </button>
          </form>

          <div className="mt-6 flex items-start gap-2 rounded-md border border-border bg-card p-3 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
            <p>
              Demonstration build — credentials are not verified. Sign in to
              open the flood management control centre with the configured
              Bengaluru pilot dataset.
            </p>
          </div>
          <RouteLink to="/" className="mt-5 block text-center text-xs text-muted-foreground hover:text-primary">
            ← Back to FloodOps landing page
          </RouteLink>
        </div>
      </div>
    </div>
  );
}

