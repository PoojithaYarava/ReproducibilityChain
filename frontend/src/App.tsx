import {
  FormEvent,
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { api, download } from "./api";

const ScoreChart = lazy(() => import("./ScoreChart"));

type User = { id: string; email: string; role: string };
type Artifact = {
  id: string;
  type: string;
  file_name: string;
  sha256: string;
  size_bytes: number;
  download_url: string;
};
type Experiment = {
  id: string;
  name: string;
  description: string;
  version: number;
  visibility: string;
  status: string;
  dataset_name: string;
  dataset_version: string;
  source_repository?: string;
  git_commit?: string;
  manifest_hash?: string;
  error_message?: string;
  created_at: string;
  configuration?: {
    model_name: string;
    hyperparameters: Record<string, unknown>;
    random_seed: number;
    environment: Record<string, string>;
  };
  metrics?: {
    values: Record<string, number>;
    confusion_matrix: number[][];
    execution_seconds: number;
  };
  artifacts: Artifact[];
  transactions: {
    transaction_hash: string;
    status: string;
    block_number: number;
    chain_id: number;
    signer_address: string;
    manifest_hash: string;
  }[];
};
type Dashboard = {
  total_experiments: number;
  verified_experiments: number;
  reproduction_attempts: number;
  failed_verification_attempts: number;
  recent_transactions: {
    transaction_hash: string;
    status: string;
    block_number: number;
    chain_id: number;
  }[];
  score_distribution: { reproduction_id: string; score: number }[];
};
type ChainStatus = {
  connected: boolean;
  contract_deployed: boolean;
  expected_chain_id: number;
  chain_id: number | null;
};
type Reproduction = {
  id: string;
  status: string;
  metrics: Record<string, number | string>;
  metric_comparison?: {
    metric: string;
    original: number;
    reproduced: number;
    absolute_difference: number;
    tolerance: number;
    within_tolerance: boolean;
  }[];
  score?: { total: number; components: Record<string, number>; reasons: string[] };
};
type Verification = {
  verified: boolean;
  artifacts_match: boolean;
  chain_match: boolean;
  artifact_checks: {
    file_name: string;
    expected_sha256: string;
    actual_sha256: string | null;
    exists: boolean;
    matches: boolean;
  }[];
  blockchain: Record<string, unknown>;
};
type Page = "dashboard" | "experiments" | "new" | "admin";

const navigation: { id: Page; label: string }[] = [
  { id: "dashboard", label: "Overview" },
  { id: "experiments", label: "Experiments" },
  { id: "new", label: "New experiment" },
];

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint: string;
}) {
  return (
    <article className="metric-card">
      <p className="eyebrow">{label}</p>
      <p className="metric-value">{value}</p>
      <p className="muted small">{hint}</p>
    </article>
  );
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem("rc-token") ?? "");
  const [user, setUser] = useState<User | null>(null);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [page, setPage] = useState<Page>("dashboard");
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [chainStatus, setChainStatus] = useState<ChainStatus | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [reproductionId, setReproductionId] = useState("");
  const [verification, setVerification] = useState<Verification | null>(null);
  const [reproduction, setReproduction] = useState<Reproduction | null>(null);
  const [adminUsers, setAdminUsers] = useState<User[]>([]);
  const [adminLogs, setAdminLogs] = useState<Record<string, unknown>[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [bootstrapToken, setBootstrapToken] = useState("");
  const [experimentName, setExperimentName] = useState("");
  const [experimentDescription, setExperimentDescription] = useState("");
  const [modelName, setModelName] = useState("logistic_regression");
  const [seed, setSeed] = useState(42);
  const [visibility, setVisibility] = useState("private");

  const selected = useMemo(
    () => experiments.find((item) => item.id === selectedId),
    [experiments, selectedId],
  );

  const refresh = useCallback(async () => {
    if (!token) return;
    const [me, all, summary, chain] = await Promise.all([
      api<User>("/api/auth/me", token),
      api<Experiment[]>("/api/experiments", token),
      api<Dashboard>("/api/dashboard", token),
      api<ChainStatus>("/api/blockchain/status", token),
    ]);
    setUser(me);
    setExperiments(all);
    setDashboard(summary);
    setChainStatus(chain);
    if (selectedId && !all.some((item) => item.id === selectedId)) {
      setSelectedId("");
    }
  }, [selectedId, token]);

  useEffect(() => {
    if (!token) return;
    let active = true;
    const load = async () => {
      try {
        await refresh();
        if (active) setError("");
      } catch (reason) {
        if (active) {
          setToken("");
          localStorage.removeItem("rc-token");
          setError(reason instanceof Error ? reason.message : "Could not load data");
        }
      }
    };
    void load();
    const interval = window.setInterval(() => void load(), 5000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [refresh, token]);

  useEffect(() => {
    if (!token || !reproductionId) return;
    let active = true;
    const poll = async () => {
      try {
        const result = await api<Reproduction>(
          `/api/reproductions/${reproductionId}`,
          token,
        );
        if (active) {
          setReproduction(result);
          if (result.status === "completed" || result.status === "failed") {
            await refresh();
          }
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Reproduction lookup failed");
      }
    };
    void poll();
    const interval = window.setInterval(() => void poll(), 1500);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [reproductionId, refresh, token]);

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<{ access_token: string; user: User }>(
        `/api/auth/${authMode === "register" ? "register" : "login"}`,
        undefined,
        {
          method: "POST",
          body: JSON.stringify({
            email: authEmail,
            password: authPassword,
            ...(authMode === "register" && bootstrapToken
              ? { bootstrap_token: bootstrapToken }
              : {}),
          }),
        },
      );
      localStorage.setItem("rc-token", result.access_token);
      setToken(result.access_token);
      setUser(result.user);
      setAuthPassword("");
      setBootstrapToken("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Authentication failed");
    } finally {
      setBusy(false);
    }
  }

  async function createExperiment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ experiment_id: string; status: string }>(
        "/api/experiments/train",
        token,
        {
          method: "POST",
          body: JSON.stringify({
            name: experimentName,
            description: experimentDescription,
            model_name: modelName,
            random_seed: seed,
            visibility,
          }),
        },
      );
      setSelectedId(result.experiment_id);
      setExperimentName("");
      setExperimentDescription("");
      setPage("experiments");
      setNotice("Training job queued. The experiment status will refresh automatically.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start training");
    } finally {
      setBusy(false);
    }
  }

  async function runExperimentAction(
    action: "register-on-chain" | "verify" | "reproductions",
  ) {
    if (!token || !selected) return;
    setBusy(true);
    setError("");
    setNotice("");
    setVerification(null);
    setReproduction(null);
    try {
      if (action === "verify") {
        const result = await api<Verification>(
          `/api/experiments/${selected.id}/verify`,
          token,
          { method: "POST" },
        );
        setVerification(result);
        setNotice(result.verified ? "Artifact and on-chain evidence both verified." : "Verification found missing or mismatched evidence.");
      } else if (action === "reproductions") {
        const result = await api<{ reproduction_id: string; status: string }>(
          `/api/experiments/${selected.id}/reproductions`,
          token,
          { method: "POST", body: JSON.stringify({}) },
        );
        setReproductionId(result.reproduction_id);
        setNotice("Independent reproduction queued using the recorded configuration.");
      } else {
        const result = await api<{
          transaction_hash: string;
          block_number: number;
          chain_id: number;
        }>(`/api/experiments/${selected.id}/register-on-chain`, token, {
          method: "POST",
        });
        setNotice(
          `Transaction confirmed in block ${result.block_number} on chain ${result.chain_id}.`,
        );
        await refresh();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Experiment action failed");
    } finally {
      setBusy(false);
    }
  }

  async function downloadReport() {
    if (!token || !selected) return;
    setBusy(true);
    setError("");
    try {
      const result = await download(`/api/experiments/${selected.id}/report`, token);
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result.fileName;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Report download failed");
    } finally {
      setBusy(false);
    }
  }

  async function showAdmin() {
    if (!token) return;
    setPage("admin");
    setError("");
    try {
      const [users, logs] = await Promise.all([
        api<User[]>("/api/admin/users", token),
        api<Record<string, unknown>[]>("/api/admin/audit-logs", token),
      ]);
      setAdminUsers(users);
      setAdminLogs(logs);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Admin view unavailable");
    }
  }

  function signOut() {
    localStorage.removeItem("rc-token");
    setToken("");
    setUser(null);
    setExperiments([]);
    setDashboard(null);
    setSelectedId("");
    setReproductionId("");
    setVerification(null);
    setReproduction(null);
  }

  if (!token) {
    return (
      <main className="auth-page">
        <section className="auth-panel">
          <div className="brand-mark">RC</div>
          <p className="eyebrow">Research evidence platform</p>
          <h1>ReproducibilityChain</h1>
          <p className="muted">
            Manage experiments, preserve reproducibility evidence, and verify
            research records from one workspace.
          </p>
          <form onSubmit={submitAuth} className="form-stack">
            <label>
              Email
              <input
                type="email"
                required
                autoComplete="email"
                value={authEmail}
                onChange={(event) => setAuthEmail(event.target.value)}
              />
            </label>
            {authMode === "register" && (
              <label>
                Administrator bootstrap token <span className="muted">(optional)</span>
                <input
                  type="password"
                  autoComplete="off"
                  value={bootstrapToken}
                  onChange={(event) => setBootstrapToken(event.target.value)}
                />
              </label>
            )}
            <label>
              Password <span className="muted">(minimum 10 characters)</span>
              <input
                type="password"
                required
                minLength={10}
                maxLength={128}
                autoComplete={authMode === "login" ? "current-password" : "new-password"}
                value={authPassword}
                onChange={(event) => setAuthPassword(event.target.value)}
              />
            </label>
            {error && <div className="callout danger">{error}</div>}
            <button className="button primary full" disabled={busy}>
              {busy ? "Please wait…" : authMode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
          <button
            className="text-button"
            onClick={() => {
              setAuthMode(authMode === "login" ? "register" : "login");
              setError("");
            }}
          >
            {authMode === "login"
              ? "New researcher? Create an account"
              : "Already registered? Sign in"}
          </button>
          <p className="fine-print">
            Passwords are hashed server-side. The browser never receives the chain
            signing key.
          </p>
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={() => setPage("dashboard")}>
          <span className="brand-mark small-mark">RC</span>
          <span>ReproducibilityChain</span>
        </a>
        <p className="sidebar-label">WORKSPACE</p>
        <nav>
          {navigation.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? "active" : ""}`}
              onClick={() => setPage(item.id)}
            >
              <span className="nav-dot" />
              {item.label}
            </button>
          ))}
          {user?.role === "admin" && (
            <button
              className={`nav-item ${page === "admin" ? "active" : ""}`}
              onClick={() => void showAdmin()}
            >
              <span className="nav-dot" />
              Administration
            </button>
          )}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot" />
          API workspace
          <button className="nav-item signout" onClick={signOut}>
            Sign out
          </button>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">LOCAL RESEARCH WORKSPACE</p>
            <p className="muted small">
              {user?.email} · {user?.role}
            </p>
          </div>
          <div className="topbar-right">
            <span className="chain-badge">
              <span className={`status-dot ${chainStatus?.contract_deployed ? "" : "offline-dot"}`} />
                {chainStatus?.contract_deployed
                  ? `Local chain ready · ${chainStatus.chain_id}`
                  : chainStatus?.connected
                    ? `RPC online · expected ${chainStatus.expected_chain_id}, registry missing`
                    : `Local chain offline · expected ${chainStatus?.expected_chain_id ?? 31337}`}
            </span>
            <button className="button primary" onClick={() => setPage("new")}>
              + New experiment
            </button>
          </div>
        </header>

        <div className="content">
          {error && (
            <div className="callout danger" role="alert">
              {error}
              <button className="dismiss" onClick={() => setError("")}>×</button>
            </div>
          )}
          {notice && (
            <div className="callout success" role="status">
              {notice}
              <button className="dismiss" onClick={() => setNotice("")}>×</button>
            </div>
          )}

          {page === "dashboard" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">OVERVIEW</p>
                  <h1>Research dashboard</h1>
                  <p className="muted">
                    Live counts from your account and the local API database.
                  </p>
                </div>
                <button className="button secondary" onClick={() => void refresh()}>
                  Refresh
                </button>
              </div>
              <section className="metric-grid">
                <MetricCard label="Experiments" value={dashboard?.total_experiments ?? "—"} hint="Owned and shared with you" />
                <MetricCard label="Verified" value={dashboard?.verified_experiments ?? "—"} hint="Artifact and chain checks passed" />
                <MetricCard label="Reproductions" value={dashboard?.reproduction_attempts ?? "—"} hint="Attempts recorded" />
                <MetricCard label="Failed checks" value={dashboard?.failed_verification_attempts ?? "—"} hint="Missing or mismatched evidence" />
              </section>
              <div className="dashboard-grid">
                <section className="panel chart-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Reproducibility scores</h2>
                      <p className="muted small">Proposed project score · maximum 100</p>
                    </div>
                  </div>
                  {dashboard?.score_distribution.length ? (
                    <div className="chart">
                      <Suspense fallback={<div className="empty-chart">Loading chart…</div>}>
                        <ScoreChart data={dashboard.score_distribution} />
                      </Suspense>
                    </div>
                  ) : (
                    <div className="empty-chart">
                      Scores will appear after a reproduction completes.
                    </div>
                  )}
                  <p className="fine-print">
                    This proposed score is not a scientifically validated
                    universal metric.
                  </p>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Recent chain transactions</h2>
                      <p className="muted small">Confirmed local development-chain writes</p>
                    </div>
                  </div>
                  {dashboard?.recent_transactions.length ? (
                    <ul className="transaction-list">
                      {dashboard.recent_transactions.map((tx) => (
                        <li key={tx.transaction_hash}>
                          <span className="status-dot" />
                          <div>
                            <strong>{tx.status}</strong>
                            <code>{tx.transaction_hash}</code>
                          </div>
                          <span className="muted small">#{tx.block_number}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="empty-state compact">
                      <p>No confirmed transactions yet.</p>
                      <p className="muted small">
                        Start Hardhat and deploy the registry before registering.
                      </p>
                    </div>
                  )}
                </section>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Recent experiments</h2>
                    <p className="muted small">Training status and evidence readiness</p>
                  </div>
                  <button className="text-button" onClick={() => setPage("experiments")}>
                    View all
                  </button>
                </div>
                <ExperimentTable
                  items={experiments.slice(0, 6)}
                  onSelect={(id) => {
                    setSelectedId(id);
                    setPage("experiments");
                  }}
                />
              </section>
            </>
          )}

          {page === "new" && (
            <section className="narrow-content">
              <div className="page-heading">
                <div>
                  <p className="eyebrow">CONTROLLED PIPELINE</p>
                  <h1>Register an experiment</h1>
                  <p className="muted">
                    The server trains only its built-in breast-cancer classifier
                    pipeline. Uploaded Python code is never executed.
                  </p>
                </div>
              </div>
              <form className="panel form-stack" onSubmit={createExperiment}>
                <label>
                  Experiment name
                  <input value={experimentName} onChange={(event) => setExperimentName(event.target.value)} required maxLength={160} />
                </label>
                <label>
                  Description
                  <textarea value={experimentDescription} onChange={(event) => setExperimentDescription(event.target.value)} rows={3} maxLength={4000} />
                </label>
                <div className="form-row">
                  <label>
                    Model architecture
                    <select value={modelName} onChange={(event) => setModelName(event.target.value)}>
                      <option value="logistic_regression">Logistic regression</option>
                      <option value="random_forest">Random forest</option>
                      <option value="decision_tree">Decision tree</option>
                    </select>
                  </label>
                  <label>
                    Random seed
                    <input type="number" min={0} max={4294967295} value={seed} onChange={(event) => setSeed(Number(event.target.value))} />
                  </label>
                </div>
                <div className="read-only-field">
                  <span className="muted small">Dataset</span>
                  <strong>Scikit-learn Breast Cancer Wisconsin · bundled version</strong>
                  <span className="fine-print">Data remains local. Dataset hash is included in the manifest.</span>
                </div>
                <label>
                  Visibility
                  <select value={visibility} onChange={(event) => setVisibility(event.target.value)}>
                    <option value="private">Private to me</option>
                    <option value="public">Public to authenticated users</option>
                  </select>
                </label>
                <div className="callout info">
                  A local Hardhat transaction is submitted separately after
                  training. No blockchain write happens during this form.
                </div>
                <div className="form-actions">
                  <button type="button" className="button secondary" onClick={() => setPage("dashboard")}>Cancel</button>
                  <button className="button primary" disabled={busy}>
                    {busy ? "Starting…" : "Train and generate evidence"}
                  </button>
                </div>
              </form>
            </section>
          )}

          {page === "experiments" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">EXPERIMENT ARCHIVE</p>
                  <h1>Experiments</h1>
                  <p className="muted">
                    Select a run to inspect evidence, transactions, and reproductions.
                  </p>
                </div>
              </div>
              <section className="panel">
                <ExperimentTable
                  items={experiments}
                  selectedId={selectedId}
                  onSelect={(id) => {
                    setSelectedId(id);
                    setVerification(null);
                    setReproduction(null);
                  }}
                />
              </section>
              {selected && (
                <ExperimentDetails
                  experiment={selected}
                  verification={verification}
                  reproduction={reproduction}
                  busy={busy}
                  onAction={runExperimentAction}
                  onDownload={() => void downloadReport()}
                  onRefresh={() => void refresh()}
                />
              )}
            </>
          )}

          {page === "admin" && user?.role === "admin" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">ACCESS CONTROL</p>
                  <h1>Administration</h1>
                  <p className="muted">User roles and append-only application audit events.</p>
                </div>
              </div>
              <section className="panel">
                <div className="panel-heading"><h2>Users</h2></div>
                <div className="table-scroll">
                  <table>
                    <thead><tr><th>Email</th><th>Role</th><th>User ID</th></tr></thead>
                    <tbody>{adminUsers.map((item) => <tr key={item.id}><td>{item.email}</td><td><span className="tag">{item.role}</span></td><td><code>{item.id}</code></td></tr>)}</tbody>
                  </table>
                </div>
              </section>
              <section className="panel">
                <div className="panel-heading"><h2>Audit history</h2></div>
                <div className="table-scroll">
                  <table>
                    <thead><tr><th>Action</th><th>User</th><th>Resource</th><th>Details</th></tr></thead>
                    <tbody>{adminLogs.map((log, index) => <tr key={String(log.id ?? index)}><td>{String(log.action)}</td><td><code>{String(log.user_id ?? "system")}</code></td><td><code>{String(log.resource_id ?? "—")}</code></td><td><code>{JSON.stringify(log.details)}</code></td></tr>)}</tbody>
                  </table>
                </div>
              </section>
            </>
          )}

          <footer className="content-footer">
            File integrity is not scientific validity · Local chain ID 31337 · No
            public testnet or public chain
          </footer>
        </div>
      </main>
    </div>
  );
}

function ExperimentTable({
  items,
  selectedId,
  onSelect,
}: {
  items: Experiment[];
  selectedId?: string;
  onSelect: (id: string) => void;
}) {
  if (!items.length) {
    return (
      <div className="empty-state">
        <div className="empty-icon">◇</div>
        <h3>No experiments yet</h3>
        <p className="muted">Train a controlled model to create an evidence manifest.</p>
      </div>
    );
  }
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr><th>Experiment</th><th>Model</th><th>Status</th><th>Evidence</th><th>Created</th></tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.id}
              className={`click-row ${selectedId === item.id ? "selected-row" : ""}`}
              onClick={() => onSelect(item.id)}
            >
              <td><strong>{item.name}</strong><span className="table-subtitle">v{item.version} · {item.visibility}</span></td>
              <td>{item.configuration?.model_name?.replaceAll("_", " ") ?? "—"}</td>
              <td><span className={`tag status-${item.status}`}>{item.status}</span></td>
              <td>{item.manifest_hash ? <span className="hash-short">{item.manifest_hash.slice(0, 18)}…</span> : "Pending"}</td>
              <td>{new Date(item.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExperimentDetails({
  experiment,
  verification,
  reproduction,
  busy,
  onAction,
  onDownload,
  onRefresh,
}: {
  experiment: Experiment;
  verification: Verification | null;
  reproduction: Reproduction | null;
  busy: boolean;
  onAction: (action: "register-on-chain" | "verify" | "reproductions") => void;
  onDownload: () => void;
  onRefresh: () => void;
}) {
  const confirmed = experiment.transactions.some((item) => item.status === "confirmed");
  return (
    <section className="panel details-panel">
      <div className="panel-heading detail-heading">
        <div>
          <p className="eyebrow">EXPERIMENT DETAIL</p>
          <h2>{experiment.name} <span className="muted">v{experiment.version}</span></h2>
          <p className="muted">{experiment.description || "No description provided."}</p>
        </div>
        <div className="action-row">
          <button className="button secondary" onClick={onRefresh}>Refresh</button>
          <button className="button secondary" onClick={onDownload} disabled={busy}>Download JSON report</button>
        </div>
      </div>
      {experiment.status === "failed" && (
        <div className="callout danger">Training failed: {experiment.error_message}</div>
      )}
      <div className="detail-grid">
        <div className="detail-section">
          <h3>Evaluation metrics</h3>
          {experiment.metrics ? (
            <div className="mini-metrics">
              {Object.entries(experiment.metrics.values).map(([name, value]) => (
                <div key={name}><span className="muted">{name}</span><strong>{value.toFixed(4)}</strong></div>
              ))}
            </div>
          ) : <p className="muted">Metrics will be available when training completes.</p>}
          {experiment.metrics && (
            <p className="fine-print">Execution {experiment.metrics.execution_seconds.toFixed(3)}s · confusion matrix: {JSON.stringify(experiment.metrics.confusion_matrix)}</p>
          )}
        </div>
        <div className="detail-section">
          <h3>Configuration</h3>
          <p><span className="muted">Dataset</span> {experiment.dataset_name} / {experiment.dataset_version}</p>
          <p><span className="muted">Architecture</span> {experiment.configuration?.model_name ?? "—"}</p>
          <p><span className="muted">Seed</span> {experiment.configuration?.random_seed ?? "—"}</p>
          <p><span className="muted">Parameters</span> <code>{JSON.stringify(experiment.configuration?.hyperparameters ?? {})}</code></p>
          {experiment.git_commit && <p><span className="muted">Commit</span> <code>{experiment.git_commit}</code></p>}
        </div>
      </div>

      <div className="detail-section">
        <div className="section-title-row">
          <h3>Evidence artifacts · SHA-256</h3>
          <span className="fine-print">Large files remain off-chain</span>
        </div>
        {experiment.artifacts.length ? (
          <div className="artifact-list">
            {experiment.artifacts.map((artifact) => (
              <div className="artifact-item" key={artifact.id}>
                <span className="artifact-type">{artifact.type.replaceAll("_", " ")}</span>
                <div><strong>{artifact.file_name}</strong><code>{artifact.sha256}</code></div>
                <span className="muted small">{formatBytes(artifact.size_bytes)}</span>
              </div>
            ))}
          </div>
        ) : <p className="muted">Evidence is being generated.</p>}
      </div>

      <div className="detail-section">
        <div className="section-title-row">
          <h3>Blockchain registry</h3>
          <span className="tag">{confirmed ? "confirmed" : "not registered"}</span>
        </div>
        {experiment.transactions.map((transaction) => (
          <div className="transaction-detail" key={transaction.transaction_hash}>
            <span>{transaction.status} · chain {transaction.chain_id} · block {transaction.block_number}</span>
            <code>{transaction.transaction_hash}</code>
          </div>
        ))}
        <div className="action-row action-row-wrap">
          <button
            className="button primary"
            onClick={() => onAction("register-on-chain")}
            disabled={busy || experiment.status !== "completed" || confirmed}
          >
            {busy ? "Working…" : "Anchor manifest on local chain"}
          </button>
          <button className="button secondary" onClick={() => onAction("verify")} disabled={busy || experiment.status !== "completed"}>
            Verify artifacts + chain
          </button>
          <button className="button secondary" onClick={() => onAction("reproductions")} disabled={busy || experiment.status !== "completed"}>
            Run reproduction
          </button>
        </div>
        {!confirmed && (
          <p className="fine-print">
            Registration requires a running local Hardhat node, deployed registry,
            and backend-only test signer. This button reports chain errors directly.
          </p>
        )}
      </div>

      {verification && (
        <div className={`callout ${verification.verified ? "success" : "warning"}`}>
          <strong>{verification.verified ? "Verification passed" : "Verification incomplete or failed"}</strong>
          <p>Artifact integrity: {verification.artifacts_match ? "match" : "failed"} · Contract commitment: {verification.chain_match ? "match" : "failed"}</p>
          <ul className="check-list">
            {verification.artifact_checks.map((check) => (
              <li key={check.file_name}>{check.matches ? "✓" : "×"} {check.file_name}: {check.matches ? "hash matches" : check.exists ? "hash mismatch" : "file missing"}</li>
            ))}
          </ul>
          {typeof verification.blockchain.error === "string" && <p>Chain error: {verification.blockchain.error}</p>}
        </div>
      )}

      {reproduction && (
        <div className={`callout ${reproduction.status === "failed" ? "danger" : "info"}`}>
          <strong>Reproduction {reproduction.status}</strong>
          {reproduction.status === "completed" && (
            <>
              <p>Metric comparison is calculated against the stored original run.</p>
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Metric</th><th>Original</th><th>Reproduced</th><th>Difference</th><th>Tolerance</th></tr></thead>
                  <tbody>
                    {(reproduction.metric_comparison ?? []).map((item) => (
                        <tr key={item.metric}>
                          <td>{item.metric}</td>
                          <td>{item.original.toFixed(4)}</td>
                          <td>{item.reproduced.toFixed(4)}</td>
                          <td>{item.absolute_difference.toFixed(4)}</td>
                          <td>{item.tolerance.toFixed(4)} · {item.within_tolerance ? "match" : "outside"}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              {reproduction.score && (
                <>
                  <p className="score-total">{reproduction.score.total}/100</p>
                  <div className="score-components">
                    {Object.entries(reproduction.score.components).map(([key, value]) => (
                      <span key={key}>{key.replaceAll("_", " ")} <strong>{value}</strong></span>
                    ))}
                  </div>
                  {reproduction.score.reasons.map((reason) => <p className="fine-print" key={reason}>{reason}</p>)}
                </>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default App;
