import {
  AlertTriangle,
  ArrowRight,
  CloudRain,
  Navigation,
  Settings,
  ShieldCheck,
  Waves,
} from "lucide-react";
import { useSim } from "@/state/simulation";
import { navigate } from "@/utils/router";

const FLOOD_MAP_IMAGE = "/floodops-landing-page.png";

const FEATURES = [
  {
    icon: CloudRain,
    title: "Rainfall Nowcast",
    text: "0–3 hour rainfall prediction for the ward",
    tone: "cyan",
  },
  {
    icon: Waves,
    title: "Flood Depth Mapping",
    text: "Street-level flood depth visualisation",
    tone: "cyan",
  },
  {
    icon: AlertTriangle,
    title: "Risk Detection",
    text: "Identify high-risk streets & drainage surcharge",
    tone: "red",
  },
  {
    icon: Navigation,
    title: "Safe Routes",
    text: "Find alternate routes avoiding flooded roads",
    tone: "cyan",
  },
] as const;

const WORKFLOW = [
  { icon: CloudRain, title: "RAIN", text: "Ingest rainfall data" },
  { icon: Settings, title: "SIMULATE", text: "Run flood model" },
  { icon: AlertTriangle, title: "DETECT RISK", text: "Identify affected areas" },
  { icon: Navigation, title: "SAFE ROUTE", text: "Find the best path" },
] as const;

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="fo-brand">
      <div className="fo-brand-mark" aria-hidden="true">
        <span>≈</span><span>≈</span><span>≈</span>
      </div>
      <div>
        <p className={compact ? "fo-brand-name fo-brand-name--compact" : "fo-brand-name"}>
          FLOOD<span>OPS</span>
        </p>
        <p className="fo-brand-tagline">Flood Monitoring &amp; Response Platform</p>
      </div>
    </div>
  );
}

export function HomePage() {
  const sim = useSim();

  return (
    <div className="fo-home">
      <header className="fo-navbar">
        <a className="fo-brand-link" href="#top" aria-label="FloodOps home">
          <Brand />
        </a>

        <nav className="fo-nav" aria-label="Landing page navigation">
          <a href="#map">Live Map</a>
          <a href="#analytics">Analytics</a>
          <a href="#resources">Resources</a>
          <a href="#about">About</a>
        </nav>

        <button className="fo-login-button" onClick={() => navigate("/login")}>
          Operator Login <ArrowRight size={17} />
        </button>
      </header>

      <main id="top" className="fo-main">
        <section className="fo-hero">
          <div className="fo-hero-copy">
            <p className="fo-eyebrow">URBAN FLOOD INTELLIGENCE</p>
            <h1 className="fo-hero-logo">FLOOD<span>OPS</span><i aria-hidden="true" /></h1>
            <h2>
              Predict Flood Risk.
              <br />
              <strong>Respond</strong> Before It Escalates.
            </h2>
            <p className="fo-description">
              A real-time monitoring and decision-support platform for tracking
              flood risk, visualising predicted water levels, identifying
              vulnerable zones, and helping authorities take faster, safer action
              during extreme rainfall.
            </p>

            <button className="fo-access-button" onClick={() => navigate("/login")}>
              <ShieldCheck size={19} />
              Access Platform
              <ArrowRight size={19} />
            </button>
            <p className="fo-secure-note">Secure access for government operators only.</p>
          </div>

          <div className="fo-map-panel" id="map">
            <img
              className="fo-map-image"
              src={FLOOD_MAP_IMAGE}
              alt="Flood risk map showing high-risk zones and a safer route"
            />

            <div className="fo-simulation-card">
              <CloudRain size={32} />
              <div>
                <b>Live Simulation</b>
                <small>{sim.metrics.clock} / 04:00</small>
                <div className="fo-progress">
                  <span style={{ width: `${Math.min(100, (sim.time / 4) * 100)}%` }} />
                </div>
              </div>
              <strong>{Math.round(Math.min(100, (sim.time / 4) * 100))}%</strong>
            </div>

            <div className="fo-legend">
              <b>Flood Depth (cm)</b>
              <span><i className="fo-depth fo-depth--severe" />&gt; 100</span>
              <span><i className="fo-depth fo-depth--high" />50 – 100</span>
              <span><i className="fo-depth fo-depth--blue" />20 – 50</span>
              <span><i className="fo-depth fo-depth--cyan" />5 – 20</span>
              <span><i className="fo-depth fo-depth--low" />&lt; 5</span>
            </div>
          </div>
        </section>

        <section className="fo-feature-grid" id="analytics" aria-label="Platform capabilities">
          {FEATURES.map(({ icon: Icon, title, text, tone }) => (
            <button className="fo-feature-card" key={title} onClick={() => navigate("/login")}>
              <span className={`fo-feature-icon fo-feature-icon--${tone}`}><Icon size={26} /></span>
              <span>
                <b>{title}</b>
                <small>{text}</small>
              </span>
              <ArrowRight className="fo-card-arrow" size={21} />
            </button>
          ))}
        </section>

        <section className="fo-workflow" id="resources" aria-label="Flood response workflow">
          {WORKFLOW.map(({ icon: Icon, title, text }, index) => (
            <span className="fo-workflow-group" key={title}>
              <span className="fo-workflow-item">
                <span className="fo-workflow-icon"><Icon size={27} /></span>
                <span>
                  <b>{title}</b>
                  <small>{text}</small>
                </span>
              </span>
              {index < WORKFLOW.length - 1 && <ArrowRight className="fo-workflow-arrow" size={25} />}
            </span>
          ))}
        </section>
      </main>

      <footer className="fo-footer" id="about">
        <div>
          <Brand compact />
        </div>
        <p className="fo-footer-links">Data-Driven Decisions <i>·</i> Safer Cities <i>·</i> Stronger Communities</p>
        <p className="fo-status"><span /> System Online <small>v2.4.1 · T+{sim.metrics.clock}</small></p>
      </footer>
    </div>
  );
}
