import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

const API_BASE_URL = "http://127.0.0.1:8000/api";

type User = { full_name?: string; email?: string };
type Agent = { id: string; name: string; role: string; model: string };
type Team = { id: string; name: string; pattern: string; agent_ids: string[] };
type Task = {
  id: string;
  team_id: string;
  framework: "langgraph" | "crewai";
  task_description: string;
  status: string;
  current_phase: string;
  final_output?: string | null;
  metadata?: Record<string, unknown>;
};
type TimelineEvent = { id: number; agent_name: string; event_type: string; description: string; created_at: string };
type TaskMessage = { id: number; from_agent: string; to_agent: string; message_type: string; content: string; created_at: string };
type LeaderboardItem = {
  agent_id: string;
  agent_name: string;
  quality_score: number;
  response_time_ms: number;
  revision_rate: number;
  token_usage: number;
  composite_score: number;
};

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail ?? "Request failed");
  return data as T;
}

type SelectOption = { value: string; label: string };

function ModernSelect({
  value,
  options,
  placeholder,
  onChange,
}: {
  value: string;
  options: SelectOption[];
  placeholder: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selected = options.find((opt) => opt.value === value);

  useEffect(() => {
    function handleOutsideClick(event: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  return (
    <div ref={rootRef} className={open ? "modern-select open" : "modern-select"}>
      <button type="button" className="modern-select-trigger" onClick={() => setOpen((prev) => !prev)}>
        <span>{selected?.label ?? placeholder}</span>
        <span className="modern-select-caret">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="modern-select-menu">
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={opt.value === value ? "modern-select-item active" : "modern-select-item"}
              onClick={() => {
                onChange(opt.value);
                setOpen(false);
              }}
            >
              <span>{opt.label}</span>
              {opt.value === value && <span className="modern-select-check">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function App() {
  const actionTone = (action: string) => {
    const value = (action || "").toLowerCase();
    if (value.includes("delegation")) return "tone-delegation";
    if (value.includes("submission")) return "tone-submission";
    if (value.includes("revision")) return "tone-revision";
    if (value.includes("synthesis")) return "tone-synthesis";
    if (value.includes("question")) return "tone-question";
    return "tone-default";
  };
  const chipTone = (key: string) => {
    let hash = 0;
    for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
    return `chip-tone-${(hash % 6) + 1}`;
  };
  const savedUser = localStorage.getItem("auth_user");
  const savedNav = localStorage.getItem("active_nav");
  const initialUser = savedUser ? (JSON.parse(savedUser) as User) : null;
  const [isSignup, setIsSignup] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(Boolean(initialUser));
  const [currentUser, setCurrentUser] = useState<User | null>(initialUser);
  const [activeNav, setActiveNav] = useState(savedNav || "Dashboard");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [agents, setAgents] = useState<Agent[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [messages, setMessages] = useState<TaskMessage[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardItem[]>([]);
  const [streamState, setStreamState] = useState("disconnected");

  const [agentName, setAgentName] = useState("");
  const [agentRole, setAgentRole] = useState("");
  const [teamName, setTeamName] = useState("");
  const [teamPattern, setTeamPattern] = useState("");
  const [teamAgentIds, setTeamAgentIds] = useState<string[]>([]);
  const [taskTeamId, setTaskTeamId] = useState("");
  const [taskPrompt, setTaskPrompt] = useState("");
  const [isSubmittingTask, setIsSubmittingTask] = useState(false);
  const [debateTeamId, setDebateTeamId] = useState("");
  const [debatePrompt, setDebatePrompt] = useState("");
  const [debateRounds, setDebateRounds] = useState(3);
  const [isSubmittingDebate, setIsSubmittingDebate] = useState(false);
  const [selectedDebateTaskId, setSelectedDebateTaskId] = useState("");
  const [debateTimeline, setDebateTimeline] = useState<TimelineEvent[]>([]);
  const [debateMessages, setDebateMessages] = useState<TaskMessage[]>([]);
  const [debateStreamState, setDebateStreamState] = useState("disconnected");

  const selectedTask = useMemo(() => tasks.find((t) => t.id === selectedTaskId), [tasks, selectedTaskId]);
  const selectedDebateTask = useMemo(() => tasks.find((t) => t.id === selectedDebateTaskId), [tasks, selectedDebateTaskId]);
  const visibleTasks = useMemo(
    () =>
      tasks
        .filter((t) => ((t.metadata as { mode?: string } | undefined)?.mode ?? "") !== "debate")
        .filter((t) => (taskTeamId ? t.team_id === taskTeamId : true))
        .slice(0, 15),
    [tasks, taskTeamId],
  );
  const debateTasks = useMemo(
    () =>
      tasks
        .filter((t) => (t.metadata as { mode?: string } | undefined)?.mode === "debate")
        .filter((t) => (debateTeamId ? t.team_id === debateTeamId : true))
        .slice(0, 2),
    [tasks, debateTeamId],
  );

  async function loadAgents() {
    const data = await apiFetch<Agent[]>("/agents");
    setAgents(data);
  }
  async function loadTeams() {
    const data = await apiFetch<Team[]>("/teams");
    setTeams(data);
    if (!taskTeamId && data.length > 0) setTaskTeamId(data[0].id);
    if (!debateTeamId && data.length > 0) setDebateTeamId(data[0].id);
  }
  async function loadPerformance() {
    const data = await apiFetch<{ leaderboard: LeaderboardItem[] }>("/performance");
    setLeaderboard(data.leaderboard ?? []);
  }
  async function loadTasks() {
    const data = await apiFetch<Task[]>("/tasks");
    setTasks(data);
    if (data.length > 0 && !selectedTaskId) setSelectedTaskId(data[0].id);
  }

  useEffect(() => {
    if (!isAuthenticated) return;
    void loadAgents();
    void loadTeams();
    void loadPerformance();
    void loadTasks();
  }, [isAuthenticated]);

  useEffect(() => {
    localStorage.setItem("active_nav", activeNav);
  }, [activeNav]);

  useEffect(() => {
    if (!isAuthenticated || activeNav !== "Collaboration" || !selectedTaskId) {
      setStreamState("disconnected");
      return;
    }

    const source = new EventSource(`${API_BASE_URL}/tasks/${selectedTaskId}/stream`);
    setStreamState("connecting");
    let lastMessagesFetchMs = 0;

    source.addEventListener("status", (event) => {
      setStreamState("connected");
      const payload = JSON.parse((event as MessageEvent).data) as { status: string; phase: string };
      setTasks((prev) => {
        let changed = false;
        const next = prev.map((task) => {
          if (task.id !== selectedTaskId) return task;
          if (task.status === payload.status && task.current_phase === payload.phase) return task;
          changed = true;
          return { ...task, status: payload.status, current_phase: payload.phase };
        });
        return changed ? next : prev;
      });
      if (payload.status === "completed" || payload.status === "failed") {
        setStreamState("completed");
        void apiFetch<Task>(`/tasks/${selectedTaskId}`).then((taskData) => {
          setTasks((prev) => {
            const filtered = prev.filter((item) => item.id !== taskData.id);
            return [taskData, ...filtered];
          });
        });
      }
    });

    source.addEventListener("timeline", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as TimelineEvent;
      setTimeline((prev) => {
        if (prev.some((item) => item.id === payload.id)) return prev;
        return [...prev, payload];
      });
      if (payload.event_type === "SYNTHESIS") {
        void apiFetch<Task>(`/tasks/${selectedTaskId}`).then((taskData) => {
          setTasks((prev) => {
            const filtered = prev.filter((item) => item.id !== taskData.id);
            return [taskData, ...filtered];
          });
        });
      }
      const now = Date.now();
      if (now - lastMessagesFetchMs > 1500) {
        lastMessagesFetchMs = now;
        void apiFetch<TaskMessage[]>(`/tasks/${selectedTaskId}/messages`).then((data) => setMessages(data));
      }
    });

    source.onerror = () => {
      if (selectedTask?.status !== "completed" && selectedTask?.status !== "failed") {
        setStreamState("disconnected");
      }
      source.close();
    };

    return () => {
      source.close();
      if (selectedTask?.status === "completed" || selectedTask?.status === "failed") {
        setStreamState("completed");
      } else {
        setStreamState("disconnected");
      }
    };
  }, [activeNav, isAuthenticated, selectedTaskId, selectedTask?.status]);

  useEffect(() => {
    if (!isAuthenticated || activeNav !== "Debate" || !selectedDebateTaskId) {
      setDebateStreamState("disconnected");
      return;
    }
    const source = new EventSource(`${API_BASE_URL}/tasks/${selectedDebateTaskId}/stream`);
    setDebateStreamState("connecting");
    source.addEventListener("status", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as { status: string; phase: string };
      setDebateStreamState(payload.status === "completed" || payload.status === "failed" ? "completed" : "connected");
      setTasks((prev) =>
        prev.map((task) =>
          task.id === selectedDebateTaskId ? { ...task, status: payload.status, current_phase: payload.phase } : task,
        ),
      );
      if (payload.status === "completed" || payload.status === "failed") {
        void apiFetch<Task>(`/tasks/${selectedDebateTaskId}`).then((taskData) =>
          setTasks((prev) => [taskData, ...prev.filter((item) => item.id !== taskData.id)]),
        );
      }
    });
    source.addEventListener("timeline", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as TimelineEvent;
      setDebateTimeline((prev) => (prev.some((item) => item.id === payload.id) ? prev : [...prev, payload]));
      void apiFetch<TaskMessage[]>(`/tasks/${selectedDebateTaskId}/messages`).then((data) => setDebateMessages(data));
    });
    source.onerror = () => {
      setDebateStreamState("disconnected");
      source.close();
    };
    return () => source.close();
  }, [activeNav, isAuthenticated, selectedDebateTaskId]);

  useEffect(() => {
    if (!taskTeamId || tasks.length === 0) return;
    const firstForTeam = tasks.find(
      (t) => t.team_id === taskTeamId && ((t.metadata as { mode?: string } | undefined)?.mode ?? "") !== "debate",
    );
    if (firstForTeam && firstForTeam.id !== selectedTaskId) {
      setSelectedTaskId(firstForTeam.id);
    }
  }, [taskTeamId, tasks, selectedTaskId]);

  useEffect(() => {
    if (!debateTeamId || tasks.length === 0 || selectedDebateTaskId) return;
    const firstDebate = tasks.find(
      (t) => t.team_id === debateTeamId && (t.metadata as { mode?: string } | undefined)?.mode === "debate",
    );
    if (firstDebate) setSelectedDebateTaskId(firstDebate.id);
  }, [debateTeamId, tasks, selectedDebateTaskId]);

  async function handleAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (!email || !password || (isSignup && (!fullName || !confirmPassword))) {
      setError("Please complete all required fields.");
      return;
    }
    if (isSignup && password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const path = isSignup ? "/auth/signup" : "/auth/login";
      const body = isSignup ? { full_name: fullName, email, password } : { email, password };
      const data = await apiFetch<{ access_token: string; user: User }>(path, { method: "POST", body: JSON.stringify(body) });
      localStorage.setItem("auth_token", data.access_token);
      localStorage.setItem("auth_user", JSON.stringify(data.user));
      setCurrentUser(data.user);
      setIsAuthenticated(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function handleLogout() {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_user");
    localStorage.removeItem("active_nav");
    setIsAuthenticated(false);
    setCurrentUser(null);
  }

  async function createAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      await apiFetch("/agents", {
        method: "POST",
        body: JSON.stringify({
          name: agentName,
          role: agentRole,
          system_prompt: `You are a ${agentRole} agent focused on task quality.`,
          tools: ["web_search"],
          model: "gemini-1.5-pro",
          temperature: 0.2,
          expertise_domain: agentRole.toLowerCase(),
          communication_style: "professional",
        }),
      });
      setAgentName("");
      setAgentRole("");
      await loadAgents();
      setNotice("Agent created.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function createTeam(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      await apiFetch("/teams", {
        method: "POST",
        body: JSON.stringify({
          name: teamName,
          pattern: teamPattern,
          description: "Team created from dashboard",
          agent_ids: teamAgentIds,
          config: { quality_threshold: 0.7, max_revisions: 0 },
        }),
      });
      setTeamName("");
      setTeamPattern("");
      setTeamAgentIds([]);
      await loadTeams();
      setNotice("Team created.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function submitTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmittingTask) return;
    setError("");
    setNotice("");
    setIsSubmittingTask(true);
    try {
      const task = await apiFetch<Task>("/tasks", {
        method: "POST",
        body: JSON.stringify({ team_id: taskTeamId, task_description: taskPrompt, framework: "langgraph" }),
      });
      setTasks((prev) => [task, ...prev]);
      setSelectedTaskId(task.id);
      setTaskPrompt("");
      setNotice("Task submitted and executed.");
      await refreshCollaboration(task.id);
      await loadPerformance();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsSubmittingTask(false);
    }
  }

  async function deleteAgent(agentId: string) {
    setError("");
    setNotice("");
    const ok = window.confirm("Delete this agent? It will be removed from existing teams.");
    if (!ok) return;
    try {
      await apiFetch(`/agents/${agentId}`, { method: "DELETE" });
      setTeamAgentIds((prev) => prev.filter((id) => id !== agentId));
      await loadAgents();
      await loadTeams();
      setNotice("Agent deleted.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function refreshDebate(taskId = selectedDebateTaskId) {
    if (!taskId) return;
    const [task, taskTimeline, taskMessages] = await Promise.all([
      apiFetch<Task>(`/tasks/${taskId}`),
      apiFetch<TimelineEvent[]>(`/tasks/${taskId}/timeline`),
      apiFetch<TaskMessage[]>(`/tasks/${taskId}/messages`),
    ]);
    setTasks((prev) => [task, ...prev.filter((item) => item.id !== task.id)]);
    setDebateTimeline(taskTimeline);
    setDebateMessages(taskMessages);
    setSelectedDebateTaskId(taskId);
  }

  async function runDebate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmittingDebate) return;
    setError("");
    setNotice("");
    setIsSubmittingDebate(true);
    try {
      const task = await apiFetch<Task>("/debates/run", {
        method: "POST",
        body: JSON.stringify({
          team_id: debateTeamId,
          task_description: debatePrompt,
          rounds: debateRounds,
          framework: "langgraph",
        }),
      });
      setTasks((prev) => [task, ...prev]);
      setSelectedDebateTaskId(task.id);
      setDebatePrompt("");
      setNotice("Debate run started.");
      await refreshDebate(task.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsSubmittingDebate(false);
    }
  }

  async function refreshCollaboration(taskId = selectedTaskId) {
    if (!taskId) return;
    const [task, taskTimeline, taskMessages] = await Promise.all([
      apiFetch<Task>(`/tasks/${taskId}`),
      apiFetch<TimelineEvent[]>(`/tasks/${taskId}/timeline`),
      apiFetch<TaskMessage[]>(`/tasks/${taskId}/messages`),
    ]);
    setTasks((prev) => {
      const filtered = prev.filter((item) => item.id !== task.id);
      return [task, ...filtered];
    });
    setTimeline(taskTimeline);
    setMessages(taskMessages);
    setSelectedTaskId(taskId);
  }

  if (!isAuthenticated) {
    return (
      <main className="auth-page">
        <div className="auth-overlay" />
        <section className="auth-panel">
          <div className="auth-card">
            <div className="auth-avatar-dot" />
            <h1>{isSignup ? "Sign up" : "Log in"}</h1>
            <p>{isSignup ? "Create your account to continue." : "Don't have an account? Sign up"}</p>
            <div className="auth-divider"><span>OR</span></div>
            <form className="auth-form" onSubmit={handleAuth}>
              {isSignup && (
                <label>
                  Your name
                  <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
                </label>
              )}
              <label>
                Your email
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </label>
              <label>
                Your password
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              {isSignup && (
                <label>
                  Confirm Password
                  <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
                </label>
              )}
              <button type="submit" disabled={busy}>
                {busy ? "Please wait..." : isSignup ? "Sign up" : "Log in"}
              </button>
            </form>
            {error && <p className="auth-message error">{error}</p>}
            <button className="switch-link" type="button" onClick={() => setIsSignup((v) => !v)}>
              {isSignup ? "Already have an account? Log In" : "Don't have an account? Sign Up"}
            </button>
          </div>
        </section>
      </main>
    );
  }

  const navItems = [
    { label: "Dashboard", icon: "◌" },
    { label: "Team Builder", icon: "◎" },
    { label: "Collaboration", icon: "◍" },
    { label: "Debate", icon: "◈" },
    { label: "Performance", icon: "◔" },
  ];
  const debateMeta = (selectedDebateTask?.metadata as { debate?: Record<string, unknown> } | undefined)?.debate ?? {};
  const argumentSpeakers = Array.from(
    new Set(
      debateMessages
        .filter((m) => m.message_type === "ARGUMENT")
        .map((m) => m.from_agent),
    ),
  );
  const verdictSpeaker = debateMessages.find((m) => m.message_type === "VERDICT")?.from_agent;
  const proName = String(debateMeta.pro_agent_name ?? argumentSpeakers[0] ?? "Pro Agent");
  const conName = String(debateMeta.con_agent_name ?? argumentSpeakers[1] ?? "Con Agent");
  const judgeName = String(debateMeta.judge_agent_name ?? verdictSpeaker ?? "Judge");
  const liveJudgeVerdict = debateMessages.find((m) => m.message_type === "VERDICT")?.content ?? "";
  const topPerformer = leaderboard[0];
  const avgResponseMs = leaderboard.length
    ? Math.round(leaderboard.reduce((sum, row) => sum + row.response_time_ms, 0) / leaderboard.length)
    : 0;
  const avgTokenUsage = leaderboard.length
    ? Math.round(leaderboard.reduce((sum, row) => sum + row.token_usage, 0) / leaderboard.length)
    : 0;
  const highRevisionAgents = leaderboard.filter((row) => row.revision_rate >= 0.5).length;
  const maxTokens = Math.max(1, ...leaderboard.map((row) => row.token_usage));
  const maxResponse = Math.max(1, ...leaderboard.map((row) => row.response_time_ms));
  const qualityPct = (value: number) => Math.max(2, Math.min(100, Math.round(value * 100)));
  const completedCount = tasks.filter((t) => t.status === "completed").length;
  const failedCount = tasks.filter((t) => t.status === "failed").length;
  const runningCount = tasks.filter((t) => t.status === "running" || t.status === "queued" || t.status === "pending").length;
  const successRate = tasks.length ? Math.round((completedCount / tasks.length) * 100) : 0;
  const avgQuality = leaderboard.length
    ? (leaderboard.reduce((sum, row) => sum + row.quality_score, 0) / leaderboard.length).toFixed(2)
    : "0.00";
  const pieStyle = {
    background: `conic-gradient(#22c55e 0 ${Math.max(1, successRate)}%, #ef4444 ${Math.max(1, successRate)}% 100%)`,
  } as const;
  const totalRuns = completedCount + failedCount;
  const activePct = totalRuns ? Math.round((completedCount / totalRuns) * 100) : 0;
  const failedPct = totalRuns ? Math.round((failedCount / totalRuns) * 100) : 0;
  const donutStyle = {
    background: `conic-gradient(#10b981 0 ${Math.max(1, activePct)}%, #f43f5e ${Math.max(1, activePct)}% 100%)`,
  } as const;
  const recentTeamStats = Array.from(new Set(tasks.map((t) => t.team_id)))
    .slice(0, 6)
    .map((teamId) => {
      const teamRuns = tasks.filter((t) => t.team_id === teamId);
      const completed = teamRuns.filter((t) => t.status === "completed").length;
      const failed = teamRuns.filter((t) => t.status === "failed").length;
      const running = teamRuns.filter((t) => t.status === "running" || t.status === "queued" || t.status === "pending").length;
      const teamName = teams.find((team) => team.id === teamId)?.name ?? teamId.slice(0, 8);
      const success = teamRuns.length ? Math.round((completed / teamRuns.length) * 100) : 0;
      return { teamId, teamName, runs: teamRuns.length, completed, failed, running, success };
    });

  return (
    <main className="workspace">
      <div className="workspace-bg" />
      <header className="topbar">
        <div className="brand compact">
          <span className="brand-dot" />
          <h1>Multi-Agent Studio</h1>
        </div>
        <div className="topbar-actions">
          <button type="button" className="icon-btn user-icon-btn" title={currentUser?.email ?? "User"} aria-label="User account">
            {((currentUser?.full_name ?? "U").trim().charAt(0) || "U").toUpperCase()}
          </button>
          <button type="button" className="icon-btn logout-icon-btn" onClick={handleLogout} title="Logout" aria-label="Logout">
            ↪
          </button>
        </div>
      </header>

      <div className={isSidebarCollapsed ? "workspace-body collapsed" : "workspace-body"}>
        <aside className={isSidebarCollapsed ? "sidebar collapsed" : "sidebar"}>
          <button
            type="button"
            className="sidebar-toggle"
            onClick={() => setIsSidebarCollapsed((prev) => !prev)}
            aria-label={isSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={isSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {isSidebarCollapsed ? "»" : "«"}
          </button>
          {navItems.map((item) => (
            <button
              key={item.label}
              type="button"
              className={item.label === activeNav ? "side-item active" : "side-item"}
              onClick={() => setActiveNav(item.label)}
            >
              <span className="side-icon">{item.icon}</span>
              {!isSidebarCollapsed && item.label}
            </button>
          ))}
        </aside>

        <section className="content">
          <div className="content-head">
            <h2>{activeNav}</h2>
            {!!notice && <p className="ok">{notice}</p>}
            {!!error && <p className="bad">{error}</p>}
          </div>

          {activeNav === "Dashboard" && (
            <div className="analytics-wrap">
              <div className="analytics-stats">
                <article className="analytics-stat stat-success">
                  <span>Success rate</span>
                  <strong>{successRate}%</strong>
                </article>
                <article className="analytics-stat stat-quality">
                  <span>Avg quality</span>
                  <strong>{avgQuality}</strong>
                </article>
                <article className="analytics-stat stat-total">
                  <span>Total runs</span>
                  <strong>{tasks.length}</strong>
                </article>
                <article className="analytics-stat stat-running">
                  <span>Running now</span>
                  <strong>{runningCount}</strong>
                </article>
              </div>

              <div className="analytics-card booking-mix">
                <h4>Run Mix</h4>
                <div className="booking-mix-body">
                  <div className="donut-wrap">
                    <div className="donut-ring" style={donutStyle}>
                      <div className="donut-center">
                        <strong>{totalRuns}</strong>
                        <span>Total</span>
                      </div>
                    </div>
                  </div>
                  <div className="mix-legends">
                    <div className="mix-item good">
                      <span>Completed runs</span>
                      <strong>{completedCount} ({activePct}%)</strong>
                    </div>
                    <div className="mix-item bad">
                      <span>Failed runs</span>
                      <strong>{failedCount} ({failedPct}%)</strong>
                    </div>
                  </div>
                </div>
              </div>

              <div className="analytics-grid">
                <div className="analytics-card full-span">
                  <h4>Stats: Recent Teams Used</h4>
                  <table className="analytics-table">
                    <thead>
                      <tr><th>Team</th><th>Total Runs</th><th>Completed</th><th>Failed</th><th>Running</th><th>Success %</th></tr>
                    </thead>
                    <tbody>
                      {recentTeamStats.length === 0 ? (
                        <tr><td colSpan={6}>No team runs yet</td></tr>
                      ) : (
                        recentTeamStats.map((row) => (
                          <tr key={row.teamId}>
                            <td>{row.teamName}</td>
                            <td><span className="metric-pill neutral">{row.runs}</span></td>
                            <td><span className="metric-pill good">{row.completed}</span></td>
                            <td><span className="metric-pill bad">{row.failed}</span></td>
                            <td><span className="metric-pill warn">{row.running}</span></td>
                            <td><span className="metric-pill info">{row.success}%</span></td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {activeNav === "Team Builder" && (
            <div className="builder-stack">
              <form className="panel builder-row agent-row" onSubmit={createAgent}>
                <div className="builder-title">
                  <h3>Create Agent</h3>
                  <p>Define a specialist with role and prompt profile.</p>
                </div>
                <div className="builder-fields">
                  <div className="field-wrap">
                    <label>Agent Name</label>
                    <input placeholder="e.g. Data Scientist" value={agentName} onChange={(e) => setAgentName(e.target.value)} required />
                  </div>
                  <div className="field-wrap">
                    <label>Role</label>
                    <input placeholder="Role (Researcher, Writer, Reviewer...)" value={agentRole} onChange={(e) => setAgentRole(e.target.value)} required />
                  </div>
                </div>
                <button>Create Agent</button>
              </form>

              <form className="panel builder-row team-row" onSubmit={createTeam}>
                <div className="builder-title">
                  <h3>Create Team</h3>
                  <p>Compose agents and choose a collaboration pattern.</p>
                </div>
                <div className="builder-fields">
                  <div className="field-wrap">
                    <label>Team Name</label>
                    <input placeholder="e.g. Data Squad" value={teamName} onChange={(e) => setTeamName(e.target.value)} required />
                  </div>
                  <div className="field-wrap">
                    <label>Pattern</label>
                    <input placeholder="Pattern (supervisor-worker / parallel / debate)" value={teamPattern} onChange={(e) => setTeamPattern(e.target.value)} required />
                  </div>
                </div>
                <div className="agent-picker wide">
                  {agents.map((agent) => {
                    const checked = teamAgentIds.includes(agent.id);
                    return (
                      <div key={agent.id} className={checked ? "agent-option checked" : "agent-option"}>
                        <label className="agent-option-main">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() =>
                              setTeamAgentIds((prev) => (prev.includes(agent.id) ? prev.filter((id) => id !== agent.id) : [...prev, agent.id]))
                            }
                          />
                          <span>{agent.name} ({agent.role})</span>
                        </label>
                        <button
                          type="button"
                          className="agent-delete-icon"
                          title="Delete agent"
                          aria-label={`Delete ${agent.name}`}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            void deleteAgent(agent.id);
                          }}
                        >
                          ×
                        </button>
                      </div>
                    );
                  })}
                </div>
                <p className="hint">Selected: {teamAgentIds.length} agent(s)</p>
                <button>Create Team</button>
              </form>

              <div className="panel builder-row configured-row">
                <div className="builder-title">
                  <h3>Configured Teams</h3>
                  <p>Recently created teams and composition snapshot.</p>
                </div>
                <div className="chips">
                  {teams.map((team) => (
                    <span key={team.id} className={`chip ${chipTone(team.id)}`}>{team.name} · {team.pattern} · {team.agent_ids.length} agents</span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeNav === "Collaboration" && (
            <div className="collab-layout">
              <form className="panel collab-card collab-runner" onSubmit={submitTask}>
                <h3>Run LangGraph Task</h3>
                <ModernSelect
                  value={taskTeamId}
                  placeholder="Select Team"
                  onChange={setTaskTeamId}
                  options={teams.map((team) => ({ value: team.id, label: team.name }))}
                />
                <textarea placeholder="Describe complex task..." value={taskPrompt} onChange={(e) => setTaskPrompt(e.target.value)} required />
                <button type="submit" disabled={isSubmittingTask}>
                  {isSubmittingTask ? "Submitting..." : "Execute Task"}
                </button>
              </form>

              <div className="panel collab-card scroll-panel">
                <h3>Task Feed</h3>
                {visibleTasks.map((task) => (
                  <button key={task.id} className={task.id === selectedTaskId ? "mini active" : "mini"} onClick={() => refreshCollaboration(task.id)}>
                    {task.status.toUpperCase()} · {task.task_description.slice(0, 42)}
                  </button>
                ))}
                {visibleTasks.length === 0 && <p className="hint">No runs for selected team yet.</p>}
              </div>

              <div className="panel collab-card scroll-panel">
                <h3>
                  Live Timeline{" "}
                  <span className={streamState === "connected" ? "live-badge on" : streamState === "completed" ? "live-badge done" : "live-badge"}>
                    {streamState}
                  </span>
                </h3>
                {timeline.map((event) => (
                  <div key={event.id} className="event-row">
                    <span className={`pill pill-event ${actionTone(event.event_type)}`}>{event.event_type}</span>
                    <span className="event-desc">{event.description}</span>
                  </div>
                ))}
              </div>

              <div className="panel collab-card scroll-panel">
                <h3>Inter-Agent Messages</h3>
                {messages.map((message) => (
                  <div key={message.id} className="msg-row">
                    <span className="pill pill-agent">{message.from_agent}</span>
                    <span className="msg-arrow">-&gt;</span>
                    <span className="pill pill-agent to">{message.to_agent}</span>
                    <span className={`pill pill-type ${actionTone(message.message_type)}`}>{message.message_type}</span>
                  </div>
                ))}
              </div>

              <div className="panel full collab-output">
                <h3><span className="output-title-pill">Final Synthesized Output</span></h3>
                <div className="output-box">{selectedTask?.final_output || "Run/select a task to view output."}</div>
              </div>
            </div>
          )}

          {activeNav === "Debate" && (
            <div className="debate-layout">
              <form className="panel debate-runner" onSubmit={runDebate}>
                <h3>Execute Debate</h3>
                <ModernSelect
                  value={debateTeamId}
                  placeholder="Select Team"
                  onChange={setDebateTeamId}
                  options={teams.map((team) => ({ value: team.id, label: team.name }))}
                />
                <label>
                  Rounds
                  <ModernSelect
                    value={String(debateRounds)}
                    placeholder="Select rounds"
                    onChange={(selected) => setDebateRounds(Number(selected))}
                    options={[2, 3, 4, 5].map((round) => ({ value: String(round), label: `${round}` }))}
                  />
                </label>
                <textarea
                  placeholder="Debate topic, e.g. Should Python remain top choice for backend AI services?"
                  value={debatePrompt}
                  onChange={(e) => setDebatePrompt(e.target.value)}
                  required
                />
                <button type="submit" disabled={isSubmittingDebate}>
                  {isSubmittingDebate ? "Starting..." : "Execute Debate Run"}
                </button>
                <p className="hint">Status: {debateStreamState}</p>
              </form>

              <div className="panel debate-history">
                <h3>Debate Runs</h3>
                {debateTasks.map((task) => (
                  <button
                    key={task.id}
                    className={task.id === selectedDebateTaskId ? "mini active" : "mini"}
                    onClick={() => refreshDebate(task.id)}
                  >
                    {task.status.toUpperCase()} · {task.task_description.slice(0, 42)}
                  </button>
                ))}
                {debateTasks.length === 0 && <p className="hint">No debates yet for this team.</p>}
                {debateTimeline.length > 0 && (
                  <p className="debate-live-events">
                    <span className="live-label">Live events</span>
                    <strong>{debateTimeline.length}</strong>
                    <span className="live-sep">·</span>
                    <span className="live-latest">Latest: {debateTimeline[debateTimeline.length - 1]?.event_type}</span>
                  </p>
                )}
              </div>

              <div className="panel debate-column pro">
                <h3>{proName}</h3>
                <div className="debate-scroll">
                  {debateMessages
                    .filter((m) => m.from_agent === proName && m.message_type === "ARGUMENT")
                    .map((m) => (
                      <div key={m.id} className="debate-bubble pro-bubble">
                        {m.content}
                      </div>
                    ))}
                </div>
              </div>

              <div className="panel debate-column con">
                <h3>{conName}</h3>
                <div className="debate-scroll">
                  {debateMessages
                    .filter((m) => m.from_agent === conName && m.message_type === "ARGUMENT")
                    .map((m) => (
                      <div key={m.id} className="debate-bubble con-bubble">
                        {m.content}
                      </div>
                    ))}
                </div>
              </div>

              <div className="panel full debate-verdict">
                <h3>{judgeName} Verdict</h3>
                <div className="output-box">
                  {selectedDebateTask?.final_output ||
                    liveJudgeVerdict ||
                    (selectedDebateTask?.status === "failed"
                      ? "Debate run failed or timed out. Please retry."
                      : "Run a debate to see judge verdict.")}
                </div>
              </div>
            </div>
          )}

          {activeNav === "Performance" && (
            <div className="performance-layout">
              <div className="performance-kpis">
                <article className="performance-kpi perf-top">
                  <span>Top Performer</span>
                  <strong>{topPerformer?.agent_name ?? "N/A"}</strong>
                  <p>Score {topPerformer?.composite_score ?? 0}</p>
                </article>
                <article className="performance-kpi perf-quality">
                  <span>Average Quality</span>
                  <strong>{avgQuality}</strong>
                  <p>Across {leaderboard.length} tracked agents</p>
                </article>
                <article className="performance-kpi perf-response">
                  <span>Average Response</span>
                  <strong>{avgResponseMs} ms</strong>
                  <p>Lower means faster agent turnaround</p>
                </article>
                <article className="performance-kpi perf-token">
                  <span>Average Tokens</span>
                  <strong>{avgTokenUsage}</strong>
                  <p>Cost proxy per agent run</p>
                </article>
                <article className="performance-kpi perf-revision">
                  <span>High Revision Agents</span>
                  <strong>{highRevisionAgents}</strong>
                  <p>Agents with revision rate {">="} 0.5</p>
                </article>
              </div>

              <div className="panel performance-table-card">
                <h3>Agent Leaderboard</h3>
                <table className="performance-table">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Agent</th>
                      <th>Composite</th>
                      <th>Quality</th>
                      <th>Response</th>
                      <th>Revisions</th>
                      <th>Tokens</th>
                    </tr>
                  </thead>
                  <tbody>
                    {leaderboard.length === 0 ? (
                      <tr>
                        <td colSpan={7}>No performance data yet. Run tasks first.</td>
                      </tr>
                    ) : (
                      leaderboard.map((row, idx) => (
                        <tr key={row.agent_id}>
                          <td>
                            <span className="rank-pill">#{idx + 1}</span>
                          </td>
                          <td className="agent-name-cell">{row.agent_name}</td>
                          <td>{row.composite_score}</td>
                          <td>
                            <div className="perf-meter-wrap">
                              <div className="perf-meter quality" style={{ width: `${qualityPct(row.quality_score)}%` }} />
                              <span>{row.quality_score}</span>
                            </div>
                          </td>
                          <td>
                            <div className="perf-meter-wrap">
                              <div className="perf-meter speed" style={{ width: `${Math.max(3, Math.round((row.response_time_ms / maxResponse) * 100))}%` }} />
                              <span>{row.response_time_ms}ms</span>
                            </div>
                          </td>
                          <td>{row.revision_rate}</td>
                          <td>
                            <div className="perf-meter-wrap">
                              <div className="perf-meter token" style={{ width: `${Math.max(3, Math.round((row.token_usage / maxTokens) * 100))}%` }} />
                              <span>{row.token_usage}</span>
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              <div className="panel performance-insights">
                <h3>Operational Insights</h3>
                <div className="insight-grid">
                  <div className="insight-item">
                    <span>Best Quality Agent</span>
                    <strong>{[...leaderboard].sort((a, b) => b.quality_score - a.quality_score)[0]?.agent_name ?? "N/A"}</strong>
                  </div>
                  <div className="insight-item">
                    <span>Fastest Agent</span>
                    <strong>{[...leaderboard].sort((a, b) => a.response_time_ms - b.response_time_ms)[0]?.agent_name ?? "N/A"}</strong>
                  </div>
                  <div className="insight-item">
                    <span>Most Token Heavy</span>
                    <strong>{[...leaderboard].sort((a, b) => b.token_usage - a.token_usage)[0]?.agent_name ?? "N/A"}</strong>
                  </div>
                  <div className="insight-item">
                    <span>Needs Coaching</span>
                    <strong>{[...leaderboard].sort((a, b) => b.revision_rate - a.revision_rate)[0]?.agent_name ?? "N/A"}</strong>
                  </div>
                </div>
              </div>
            </div>
          )}

        </section>
      </div>
    </main>
  );
}

export default App;
