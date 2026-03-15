import { useState, useCallback, useRef, useMemo } from "react";

// ─── API base URL ─────────────────────────────────────────────────────────────
// Set VITE_API_URL at build time to point to your AWS App Runner backend URL.
// In GitHub Codespaces we intentionally use same-origin (`""`) so Vite's
// `/api` proxy handles backend routing and avoids browser CORS preflight issues.
const configuredApiBase = (import.meta.env.VITE_API_URL || "").trim();
const isCodespacesHost =
  typeof window !== "undefined" && window.location.hostname.endsWith(".app.github.dev");
const API_BASE = isCodespacesHost ? "" : configuredApiBase;

// ─── Sample code snippets (pre-loaded with intentional issues for demo) ───────
const SAMPLE_CODE = {
  python: `import requests
import os

# BAD: hardcoded secret — should use os.environ
password = "<HARDCODED_SECRET_DO_NOT_USE>"
API_KEY = "<HARDCODED_API_KEY_DO_NOT_USE>"

def fetch_user_data(user_id):
    # BAD: no error handling on external call
    response = requests.get(f"https://api.example.com/users/{user_id}",
                           headers={"Authorization": API_KEY})
    data = response.json()
    return data

def process_users(user_ids):
    results = ""
    for uid in user_ids:
        # BAD: string concatenation in loop (O(n²))
        results += str(fetch_user_data(uid))
    return results

try:
    process_users([1, 2, 3])
except:
    # BAD: bare except swallows SystemExit and KeyboardInterrupt
    pass`,

  java: `import java.sql.*;
import java.util.*;

public class UserService {
    // BAD: hardcoded credential
    private static String DB_PASSWORD = "<HARDCODED_DB_PASSWORD_DO_NOT_USE>";
    private static Connection conn;

    public List<String> getAllUsers() {
        List<String> users = new ArrayList<>();
        try {
            Statement stmt = conn.createStatement();
            // BAD: SQL injection — never concatenate user input
            ResultSet rs = stmt.executeQuery("SELECT * FROM users");
            while (rs.next()) {
                // BAD: System.out instead of SLF4J logger
                System.out.println("Found user: " + rs.getString("name"));
                users.add(rs.getString("name"));
            }
        } catch (Exception e) {
            // BAD: empty catch block silently swallows the exception
        }
        return users;
    }
}`,

  mulesoft: `<?xml version="1.0" encoding="UTF-8"?>
<mule xmlns="http://www.mulesoft.org/schema/mule/core"
      xmlns:http="http://www.mulesoft.org/schema/mule/http"
      xmlns:db="http://www.mulesoft.org/schema/mule/db">

  <!-- BAD: hardcoded credentials — use \${secure::db.password} -->
  <db:config name="Database_Config">
    <db:my-sql-connection host="localhost" port="3306"
                          user="<HARDCODED_USER>" password="<HARDCODED_PASSWORD_DO_NOT_USE>"
                          database="production_db"/>
  </db:config>

  <flow name="getUsersFlow">
    <http:listener config-ref="HTTP_Listener_config" path="/users"/>
    <!-- BAD: no error handler on this flow -->
    <db:select config-ref="Database_Config">
      <db:sql>SELECT * FROM users WHERE id = #[attributes.queryParams.id]</db:sql>
    </db:select>
    <!-- BAD: DEBUG logger should never run in production -->
    <logger level="DEBUG" message="Result: #[payload]"/>
  </flow>

  <!-- BAD: orphaned flow — never referenced by any flow-ref -->
  <flow name="unusedHelperFlow">
    <logger level="INFO" message="This flow is never called"/>
  </flow>
</mule>`,
};

// ─── Severity badge ────────────────────────────────────────────────────────────
function SeverityBadge({ severity }) {
  const styles = {
    CRITICAL: "bg-red-500/20 text-red-300 border border-red-500/40",
    WARNING:  "bg-amber-500/20 text-amber-300 border border-amber-500/40",
    INFO:     "bg-sky-500/20 text-sky-300 border border-sky-500/40",
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${styles[severity] || styles.INFO}`}>
      {severity}
    </span>
  );
}

// ─── Risk badge ────────────────────────────────────────────────────────────────
function RiskBadge({ risk }) {
  const styles = {
    HIGH:   "text-red-400",
    MEDIUM: "text-amber-400",
    LOW:    "text-emerald-400",
  };
  return (
    <span className={`font-bold font-mono ${styles[risk] || "text-slate-400"}`}>
      {risk}
    </span>
  );
}

// ─── Animated score ring ──────────────────────────────────────────────────────
function ScoreRing({ score, label }) {
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color = score >= 80 ? "#34d399" : score >= 60 ? "#fbbf24" : "#f87171";
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="100" height="100" className="-rotate-90">
        <circle cx="50" cy="50" r={radius} fill="none" stroke="#1e293b" strokeWidth="8" />
        <circle
          cx="50" cy="50" r={radius} fill="none"
          stroke={color} strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 1s ease" }}
        />
      </svg>
      <div className="relative -mt-16 flex flex-col items-center">
        <span className="text-2xl font-bold font-mono text-white">{score}</span>
        <span className="text-xs text-slate-400 mt-0.5">/100</span>
      </div>
      <div className="mt-8 text-xs text-slate-400 font-mono text-center">{label}</div>
    </div>
  );
}

// ─── Side-by-side diff viewer ─────────────────────────────────────────────────
function DiffViewer({ original, refactored }) {
  const [view, setView] = useState("split");
  if (!refactored) return null;

  const origLines = (original || "").split("\n");
  const refLines  = (refactored || "").split("\n");

  return (
    <div>
      <div className="flex gap-2 mb-3">
        {["split", "original", "refactored"].map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`px-3 py-1 rounded text-xs font-mono transition-colors ${
              view === v
                ? "bg-orange-600 text-white"
                : "bg-slate-800 text-slate-400 hover:bg-slate-700"
            }`}
          >
            {v}
          </button>
        ))}
      </div>
      {view === "split" ? (
        <div className="grid grid-cols-2 gap-2">
          <div>
            <div className="text-xs text-red-400 font-mono mb-1 px-1">● Original</div>
            <pre className="bg-slate-900 rounded-lg p-4 text-xs font-mono text-red-200 overflow-auto max-h-96 border border-red-900/30">
              {origLines.map((line, i) => (
                <div key={i} className="flex">
                  <span className="text-slate-600 w-8 shrink-0 select-none">{i + 1}</span>
                  <span>{line}</span>
                </div>
              ))}
            </pre>
          </div>
          <div>
            <div className="text-xs text-emerald-400 font-mono mb-1 px-1">● Refactored by Nova Pro</div>
            <pre className="bg-slate-900 rounded-lg p-4 text-xs font-mono text-emerald-200 overflow-auto max-h-96 border border-emerald-900/30">
              {refLines.map((line, i) => (
                <div key={i} className="flex">
                  <span className="text-slate-600 w-8 shrink-0 select-none">{i + 1}</span>
                  <span>{line}</span>
                </div>
              ))}
            </pre>
          </div>
        </div>
      ) : (
        <pre className="bg-slate-900 rounded-lg p-4 text-xs font-mono text-slate-300 overflow-auto max-h-96 border border-slate-700">
          {(view === "original" ? origLines : refLines).map((line, i) => (
            <div key={i} className="flex">
              <span className="text-slate-600 w-8 shrink-0 select-none">{i + 1}</span>
              <span>{line}</span>
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}

// ─── Expandable issue card with Nova coaching insight ─────────────────────────
function normalizeIssueKey(value) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function extractIssueOrdinal(value) {
  const digits = String(value ?? "").match(/(\d+)/g);
  if (!digits || digits.length === 0) return "";
  return String(Number(digits[digits.length - 1]));
}

function resolveCoachingInsight(issue, coaching, issueIndex) {
  if (!Array.isArray(coaching) || coaching.length === 0) return null;

  const issueKey = normalizeIssueKey(issue.id);
  const issueOrdinal = extractIssueOrdinal(issue.id);

  const directMatch = coaching.find((item) => {
    const coachingId = item?.issue_id ?? item?.issueId ?? item?.id;
    return normalizeIssueKey(coachingId) === issueKey;
  });
  if (directMatch) return directMatch;

  if (issueOrdinal) {
    const ordinalMatch = coaching.find((item) => {
      const coachingId = item?.issue_id ?? item?.issueId ?? item?.id;
      return extractIssueOrdinal(coachingId) === issueOrdinal;
    });
    if (ordinalMatch) return ordinalMatch;
  }

  // Best effort: if ordering is preserved, surface coaching by index.
  return coaching[issueIndex] || null;
}

function IssueCard({ issue, coaching, issueIndex }) {
  const [expanded, setExpanded] = useState(false);
  const insight = resolveCoachingInsight(issue, coaching, issueIndex);

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 overflow-hidden transition-all duration-200 hover:border-slate-600">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-4 py-3 flex items-start gap-3"
      >
        <SeverityBadge severity={issue.severity} />
        <div className="flex-1 min-w-0">
          <div className="text-slate-200 text-sm leading-snug">{issue.description}</div>
          <div className="text-slate-500 text-xs mt-1">
            {issue.rule_id} · line {issue.line_range}
          </div>
        </div>
        <span className="text-slate-500 text-sm mt-0.5">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="border-t border-slate-700/50 bg-slate-900/40 px-4 py-3 text-sm space-y-2">
          {insight ? (
            <>
              <div>
                <span className="text-orange-400 font-bold text-xs uppercase tracking-wider">Principle</span>
                <p className="text-slate-300 mt-0.5">{insight.principle}</p>
              </div>
              <div>
                <span className="text-orange-400 font-bold text-xs uppercase tracking-wider">Why it matters</span>
                <p className="text-slate-300 mt-0.5">{insight.why_it_matters}</p>
              </div>
              <div>
                <span className="text-amber-400 font-bold text-xs uppercase tracking-wider">Production Risk</span>
                <p className="text-slate-300 mt-0.5">{insight.production_risk}</p>
              </div>
              {insight.reference && (
                <div className="text-xs text-slate-500">📚 {insight.reference}</div>
              )}
              <div className="text-xs text-slate-600 pt-1">Coached by Amazon Nova Lite</div>
            </>
          ) : (
            <>
              <div>
                <span className="text-orange-400 font-bold text-xs uppercase tracking-wider">Issue details</span>
                <p className="text-slate-300 mt-0.5">{issue.description}</p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="text-slate-500">Rule</span>
                  <p className="text-slate-300">{issue.rule_id}</p>
                </div>
                <div>
                  <span className="text-slate-500">Line</span>
                  <p className="text-slate-300">{issue.line_range}</p>
                </div>
              </div>
              <div className="text-xs text-slate-500">Detailed coaching is unavailable for this finding, but the issue metadata is shown above.</div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Tab component ────────────────────────────────────────────────────────────
function Tab({ label, active, onClick, count }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-mono transition-all border-b-2 ${
        active
          ? "border-orange-500 text-orange-300"
          : "border-transparent text-slate-500 hover:text-slate-300"
      }`}
    >
      {label}
      {count !== undefined && (
        <span className={`ml-2 px-1.5 py-0.5 rounded text-xs ${
          active ? "bg-orange-500/30 text-orange-300" : "bg-slate-700 text-slate-400"
        }`}>
          {count}
        </span>
      )}
    </button>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [language, setLanguage]   = useState("python");
  const [code, setCode]           = useState(SAMPLE_CODE.python);
  const [loading, setLoading]     = useState(false);
  const [result, setResult]       = useState(null);
  const [error, setError]         = useState(null);
  const [activeTab, setActiveTab] = useState("findings");
  const [uploadMode, setUploadMode] = useState(false);
  const fileRef = useRef(null);

  const handleLanguageChange = useCallback((lang) => {
    setLanguage(lang);
    setCode(SAMPLE_CODE[lang]);
    setResult(null);
    setError(null);
  }, []);

  const handleReview = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    console.log("API_BASE:", API_BASE);      
    console.log("Calling:", `${API_BASE}/api/review`);
    try {
      const res = await fetch(`${API_BASE}/api/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, language }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Review failed");
      }
      setResult(await res.json());
      setActiveTab("findings");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [code, language]);

  const handleZipUpload = useCallback(async (file) => {
    setLoading(true);
    setError(null);
    setResult(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(`${API_BASE}/api/review/mulesoft-project`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Upload failed");
      }
      setResult(await res.json());
      setActiveTab("findings");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Derived data
  const issues   = result?.analysis?.issues || [];
  const coaching = useMemo(() => {
    if (Array.isArray(result?.coaching?.coaching)) return result.coaching.coaching;
    if (Array.isArray(result?.coaching)) return result.coaching;
    return [];
  }, [result]);
  const changes  = result?.refactor?.changes_made || [];
  const validation = result?.validation || {};

  const critical = issues.filter((i) => i.severity === "CRITICAL").length;
  const warnings = issues.filter((i) => i.severity === "WARNING").length;
  const infos    = issues.filter((i) => i.severity === "INFO").length;

  return (
    <div
      className="min-h-screen bg-slate-950 text-slate-100"
      style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@700;800&display=swap');
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        textarea { resize: none; }
      `}</style>

      {/* ── Header ── */}
      <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* AWS orange accent */}
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-orange-500 to-amber-700 flex items-center justify-center text-white font-bold text-sm">P</div>
            <div>
              <div className="text-white font-bold text-lg" style={{ fontFamily: "'Syne', sans-serif" }}>
                PolyDev <span className="text-orange-400">Coach</span>
              </div>
              <div className="text-slate-500 text-xs">Multi-Agent AI Code Review · Amazon Nova on AWS Bedrock</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {["python", "java", "mulesoft"].map((lang) => (
              <button
                key={lang}
                onClick={() => handleLanguageChange(lang)}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-all ${
                  language === lang
                    ? "bg-orange-600 text-white shadow-lg shadow-orange-900/30"
                    : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                }`}
              >
                {lang === "mulesoft" ? "MuleSoft" : lang.charAt(0).toUpperCase() + lang.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6 grid grid-cols-2 gap-6 h-[calc(100vh-73px)]">

        {/* ── Left: Code Input ── */}
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <div className="text-xs text-slate-500 uppercase tracking-wider">Code Input</div>
            {language === "mulesoft" && (
              <div className="flex gap-2">
                <button
                  onClick={() => setUploadMode(false)}
                  className={`text-xs px-2 py-1 rounded ${!uploadMode ? "bg-orange-700 text-white" : "text-slate-400 hover:text-slate-200"}`}
                >
                  Paste XML
                </button>
                <button
                  onClick={() => setUploadMode(true)}
                  className={`text-xs px-2 py-1 rounded ${uploadMode ? "bg-orange-700 text-white" : "text-slate-400 hover:text-slate-200"}`}
                >
                  Upload Project .zip
                </button>
              </div>
            )}
          </div>

          {uploadMode && language === "mulesoft" ? (
            <div
              onClick={() => fileRef.current?.click()}
              className="flex-1 rounded-xl border-2 border-dashed border-slate-700 hover:border-orange-600 flex flex-col items-center justify-center gap-3 cursor-pointer transition-colors"
            >
              <div className="text-4xl">📦</div>
              <div className="text-slate-400 text-sm">Click to upload MuleSoft project .zip</div>
              <div className="text-slate-600 text-xs">Max 50MB · Uses mulesoft_package_validator internally</div>
              <input
                ref={fileRef} type="file" accept=".zip" className="hidden"
                onChange={(e) => e.target.files[0] && handleZipUpload(e.target.files[0])}
              />
            </div>
          ) : (
            <textarea
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="flex-1 rounded-xl bg-slate-900 border border-slate-700/60 text-slate-300 text-xs p-4 font-mono leading-relaxed focus:outline-none focus:border-orange-600 transition-colors"
              placeholder="Paste your code here..."
              spellCheck={false}
            />
          )}

          <button
            onClick={handleReview}
            disabled={loading || (!uploadMode && !code.trim())}
            className="w-full py-3 rounded-xl font-bold text-sm transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: loading
                ? "#92400e"
                : "linear-gradient(135deg, #ea580c, #b45309)",
            }}
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-orange-300 border-t-transparent rounded-full animate-spin" />
                Running Nova Pipeline...
              </span>
            ) : (
              "⚡ Analyze with Amazon Nova"
            )}
          </button>

          {error && (
            <div className="rounded-xl bg-red-950/50 border border-red-800/50 p-3 text-red-300 text-xs">
              ❌ {error}
            </div>
          )}

          {/* Pipeline status — shown during load */}
          {loading && (
            <div className="rounded-xl bg-slate-900/60 border border-slate-700/40 p-4 text-xs space-y-2">
              <div className="text-slate-500 uppercase tracking-wider text-xs mb-3">Amazon Nova Pipeline</div>
              {[
                { icon: "🔍", label: "Static Analyzer (mulesoft_package_validator)", model: "" },
                { icon: "🧠", label: "Analyzer Agent", model: "Nova Micro" },
                { icon: "🎓", label: "Coach Agent (Bedrock Knowledge Base RAG)", model: "Nova Lite" },
                { icon: "⚒️",  label: "Refactor Agent", model: "Nova Pro" },
                { icon: "✅", label: "Validator Agent", model: "Nova Lite" },
                { icon: "✨", label: "Optimizer Agent", model: "Nova Micro" },
              ].map((step, i) => (
                <div key={i} className="flex items-center gap-2 text-slate-400">
                  <span>{step.icon}</span>
                  <span className="flex-1">{step.label}</span>
                  {step.model && (
                    <span className="text-orange-600 text-xs font-mono">{step.model}</span>
                  )}
                  <span className="w-3 h-3 border border-orange-500 border-t-transparent rounded-full animate-spin" />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Right: Results ── */}
        <div className="flex flex-col gap-4 min-h-0">
          {!result ? (
            <div className="flex-1 rounded-xl border border-slate-800 bg-slate-900/30 flex flex-col items-center justify-center gap-4 text-center px-8">
              <div className="text-5xl opacity-30">🛡️</div>
              <div className="text-slate-500 text-sm">
                PolyDev Coach runs a 6-agent pipeline powered by
                <span className="text-orange-400"> Amazon Nova</span> on AWS Bedrock.
                <br /><br />
                Static analysis from <span className="text-orange-400">mulesoft_package_validator</span> feeds
                Nova Micro → Nova Lite (RAG) → Nova Pro → Nova Lite → Nova Micro.
              </div>
            </div>
          ) : (
            <>
              {/* Summary bar */}
              <div className="rounded-xl bg-slate-900/60 border border-slate-700/40 p-3 grid grid-cols-5 gap-2 text-center text-xs">
                <div>
                  <div className="text-red-400 font-bold text-lg">{critical}</div>
                  <div className="text-slate-500">Critical</div>
                </div>
                <div>
                  <div className="text-amber-400 font-bold text-lg">{warnings}</div>
                  <div className="text-slate-500">Warnings</div>
                </div>
                <div>
                  <div className="text-sky-400 font-bold text-lg">{infos}</div>
                  <div className="text-slate-500">Info</div>
                </div>
                <div>
                  <div className="font-bold text-lg">
                    <RiskBadge risk={result.analysis?.overall_risk} />
                  </div>
                  <div className="text-slate-500">Risk</div>
                </div>
                <div>
                  <div className="text-slate-300 font-bold text-lg">{result.processing_time_seconds}s</div>
                  <div className="text-slate-500">Time</div>
                </div>
              </div>

              {/* Tabs */}
              <div className="flex border-b border-slate-800">
                <Tab label="Findings"     active={activeTab === "findings"}  onClick={() => setActiveTab("findings")}  count={issues.length} />
                <Tab label="Refactor"     active={activeTab === "refactor"}  onClick={() => setActiveTab("refactor")}  count={changes.length} />
                <Tab label="Quality Score" active={activeTab === "score"}    onClick={() => setActiveTab("score")} />
              </div>

              {/* Tab content */}
              <div className="flex-1 overflow-y-auto pr-1 space-y-3">

                {activeTab === "findings" && (
                  <>
                    {issues.length === 0 ? (
                      <div className="text-center text-emerald-400 py-8 text-sm">
                        ✅ No issues found — code looks clean!
                      </div>
                    ) : (
                      issues.map((issue, idx) => (
                        <IssueCard
                          key={issue.id}
                          issue={issue}
                          coaching={coaching}
                          issueIndex={idx}
                        />
                      ))
                    )}
                  </>
                )}

                {activeTab === "refactor" && (
                  <div className="space-y-4">
                    {changes.length > 0 && (
                      <div className="rounded-xl bg-slate-900/60 border border-slate-700/40 p-3 space-y-1.5">
                        <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">
                          Changes Made by Nova Pro
                        </div>
                        {changes.map((c, i) => (
                          <div key={i} className="flex gap-2 text-xs">
                            <span className="text-emerald-400">✓</span>
                            <span className="text-slate-300">[{c.issue_id}] {c.change_description}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    <DiffViewer original={code} refactored={result.refactor?.refactored_code} />
                    <div className="text-xs text-slate-500 text-right">
                      Nova Pro confidence: {Math.round((result.refactor?.confidence || 0) * 100)}%
                    </div>
                  </div>
                )}

                {activeTab === "score" && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-3 gap-4 pt-2">
                      <ScoreRing score={validation.correctness_score || 0} label="Correctness" />
                      <ScoreRing score={validation.issues_addressed || 0}  label="Issues Addressed" />
                      <ScoreRing score={Math.round((result.refactor?.confidence || 0) * 100)} label="Confidence" />
                    </div>
                    <div className="rounded-xl bg-slate-900/60 border border-slate-700/40 p-4 space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-slate-500">Logic Preserved</span>
                        <span className={validation.logic_preserved ? "text-emerald-400" : "text-red-400"}>
                          {validation.logic_preserved ? "✓ Yes" : "✗ No"}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500">Overall Risk</span>
                        <RiskBadge risk={result.analysis?.overall_risk} />
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500">Pipeline Time</span>
                        <span className="text-slate-300">{result.processing_time_seconds}s</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500">Validated by</span>
                        <span className="text-orange-400 text-xs font-mono">Amazon Nova Lite</span>
                      </div>
                    </div>
                    {validation.flags?.length > 0 && (
                      <div className="rounded-xl bg-amber-950/30 border border-amber-800/30 p-3">
                        <div className="text-amber-400 text-xs font-bold mb-2 uppercase tracking-wider">
                          Validator Flags
                        </div>
                        {validation.flags.map((f, i) => (
                          <div key={i} className="text-amber-300 text-xs">⚠ {f}</div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
