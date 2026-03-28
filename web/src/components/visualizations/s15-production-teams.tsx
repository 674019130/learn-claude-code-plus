"use client";

import { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useSteppedVisualization } from "@/hooks/useSteppedVisualization";
import { StepControls } from "@/components/visualizations/shared/step-controls";

// --- Types ---

type AgentType = "explore" | "plan" | "code" | "test";
type SpawnMode = "foreground" | "background";
type AgentStatus = "active" | "working" | "completed" | "blocking" | "shutdown";

interface AgentBox {
  id: string;
  label: string;
  pid: number;
  type: AgentType | "lead";
  status: AgentStatus;
  spawnMode?: SpawnMode;
}

interface MessageArrow {
  from: string;
  to: string;
  label: string;
}

interface StepState {
  agents: AgentBox[];
  typeBadges: AgentType[];
  showConfig: boolean;
  showTaskBoard: boolean;
  blockingLine: { from: string; to: string } | null;
  messages: MessageArrow[];
  inboxItems: string[];
  shutdownAll: boolean;
}

// --- Constants ---

const TYPE_COLORS: Record<AgentType, { bg: string; text: string; border: string; dot: string }> = {
  explore: { bg: "bg-blue-100 dark:bg-blue-900/30", text: "text-blue-600 dark:text-blue-400", border: "border-blue-500", dot: "bg-blue-500" },
  plan:    { bg: "bg-green-100 dark:bg-green-900/30", text: "text-green-600 dark:text-green-400", border: "border-green-500", dot: "bg-green-500" },
  code:    { bg: "bg-orange-100 dark:bg-orange-900/30", text: "text-orange-600 dark:text-orange-400", border: "border-orange-500", dot: "bg-orange-500" },
  test:    { bg: "bg-amber-100 dark:bg-amber-900/30", text: "text-amber-600 dark:text-amber-400", border: "border-amber-500", dot: "bg-amber-500" },
};

const LEAD_COLORS = {
  bg: "bg-red-50 dark:bg-red-900/20",
  text: "text-red-600 dark:text-red-400",
  border: "border-red-500",
  dot: "bg-red-500",
};

function computeStepState(step: number): StepState {
  switch (step) {
    case 0:
      return {
        agents: [{ id: "lead", label: "Lead", pid: 1000, type: "lead", status: "active" }],
        typeBadges: [],
        showConfig: false,
        showTaskBoard: false,
        blockingLine: null,
        messages: [],
        inboxItems: [],
        shutdownAll: false,
      };
    case 1:
      return {
        agents: [{ id: "lead", label: "Lead", pid: 1000, type: "lead", status: "active" }],
        typeBadges: [],
        showConfig: true,
        showTaskBoard: true,
        blockingLine: null,
        messages: [],
        inboxItems: [],
        shutdownAll: false,
      };
    case 2:
      return {
        agents: [{ id: "lead", label: "Lead", pid: 1000, type: "lead", status: "active" }],
        typeBadges: ["explore", "plan", "code", "test"],
        showConfig: true,
        showTaskBoard: true,
        blockingLine: null,
        messages: [],
        inboxItems: [],
        shutdownAll: false,
      };
    case 3:
      return {
        agents: [
          { id: "lead", label: "Lead", pid: 1000, type: "lead", status: "blocking" },
          { id: "researcher", label: "researcher", pid: 1001, type: "explore", status: "working", spawnMode: "foreground" },
        ],
        typeBadges: ["explore", "plan", "code", "test"],
        showConfig: true,
        showTaskBoard: true,
        blockingLine: { from: "lead", to: "researcher" },
        messages: [],
        inboxItems: [],
        shutdownAll: false,
      };
    case 4:
      return {
        agents: [
          { id: "lead", label: "Lead", pid: 1000, type: "lead", status: "active" },
          { id: "researcher", label: "researcher", pid: 1001, type: "explore", status: "completed", spawnMode: "foreground" },
          { id: "coder-a", label: "coder-a", pid: 1002, type: "code", status: "working", spawnMode: "background" },
          { id: "coder-b", label: "coder-b", pid: 1003, type: "code", status: "working", spawnMode: "background" },
        ],
        typeBadges: ["explore", "plan", "code", "test"],
        showConfig: true,
        showTaskBoard: true,
        blockingLine: null,
        messages: [],
        inboxItems: [],
        shutdownAll: false,
      };
    case 5:
      return {
        agents: [
          { id: "lead", label: "Lead", pid: 1000, type: "lead", status: "active" },
          { id: "coder-a", label: "coder-a", pid: 1002, type: "code", status: "completed", spawnMode: "background" },
          { id: "coder-b", label: "coder-b", pid: 1003, type: "code", status: "working", spawnMode: "background" },
        ],
        typeBadges: ["explore", "plan", "code", "test"],
        showConfig: true,
        showTaskBoard: true,
        blockingLine: null,
        messages: [{ from: "coder-a", to: "lead", label: "result ready" }],
        inboxItems: ["coder-a: task completed"],
        shutdownAll: false,
      };
    case 6:
      return {
        agents: [
          { id: "lead", label: "Lead", pid: 1000, type: "lead", status: "active" },
          { id: "coder-a", label: "coder-a", pid: 1002, type: "code", status: "completed", spawnMode: "background" },
          { id: "coder-b", label: "coder-b", pid: 1003, type: "code", status: "completed", spawnMode: "background" },
        ],
        typeBadges: ["explore", "plan", "code", "test"],
        showConfig: true,
        showTaskBoard: true,
        blockingLine: null,
        messages: [{ from: "lead", to: "coder-b", label: "sendMessage" }],
        inboxItems: ["coder-a: task completed", "coder-b: task completed"],
        shutdownAll: false,
      };
    case 7:
      return {
        agents: [
          { id: "lead", label: "Lead", pid: 1000, type: "lead", status: "shutdown" },
          { id: "coder-a", label: "coder-a", pid: 1002, type: "code", status: "shutdown", spawnMode: "background" },
          { id: "coder-b", label: "coder-b", pid: 1003, type: "code", status: "shutdown", spawnMode: "background" },
        ],
        typeBadges: [],
        showConfig: false,
        showTaskBoard: false,
        blockingLine: null,
        messages: [],
        inboxItems: [],
        shutdownAll: true,
      };
    default:
      return {
        agents: [],
        typeBadges: [],
        showConfig: false,
        showTaskBoard: false,
        blockingLine: null,
        messages: [],
        inboxItems: [],
        shutdownAll: false,
      };
  }
}

const STEPS = [
  { title: "Single Agent", description: "The Lead agent runs alone -- a single process handling all tasks sequentially. No team infrastructure exists yet." },
  { title: "Create Team", description: "Lead initializes the team: config.json defines agent types and limits, a shared task board coordinates work." },
  { title: "Type Registry", description: "Four agent types registered: explore (research), plan (architecture), code (implementation), test (validation). Each has its own system prompt and tool access." },
  { title: "Foreground Spawn", description: "Lead spawns 'researcher' as a foreground agent (explore type). Lead blocks and waits -- it cannot proceed until researcher returns." },
  { title: "Foreground Complete", description: "Researcher returns its result, Lead resumes. Lead then spawns two background agents (coder-a, coder-b) -- Lead stays active while they work in parallel." },
  { title: "Background Running", description: "coder-a completes and sends a notification to Lead's inbox. coder-b is still working. Lead can check inbox anytime without blocking." },
  { title: "SendMessage", description: "Lead sends a message to coder-b with additional instructions. coder-b receives, adjusts, and completes its task." },
  { title: "Shutdown", description: "All work done. Lead sends shutdown signal to all agents, waits for cleanup, then the team is dissolved. Resources are released." },
];

// --- Sub-components ---

function TypeBadge({ type }: { type: AgentType }) {
  const colors = TYPE_COLORS[type];
  return (
    <motion.span
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${colors.bg} ${colors.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${colors.dot}`} />
      {type}
    </motion.span>
  );
}

function ProcessBox({ agent, isShutdown }: { agent: AgentBox; isShutdown: boolean }) {
  const isLead = agent.type === "lead";
  const colors = isLead ? LEAD_COLORS : TYPE_COLORS[agent.type as AgentType];
  const isBlocking = agent.status === "blocking";
  const isCompleted = agent.status === "completed";
  const isWorking = agent.status === "working";
  const isDying = agent.status === "shutdown";

  const statusIndicator = (() => {
    if (isDying) return { color: "bg-zinc-400", label: "shutdown" };
    if (isCompleted) return { color: "bg-green-500", label: "completed" };
    if (isBlocking) return { color: "bg-yellow-500", label: "blocking..." };
    if (isWorking) return { color: "bg-blue-500", label: "working..." };
    return { color: colors.dot, label: "active" };
  })();

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.8, y: 10 }}
      animate={{
        opacity: isDying ? (isShutdown ? 0.3 : 1) : isBlocking ? 0.5 : 1,
        scale: isDying ? 0.95 : 1,
        y: 0,
      }}
      exit={{ opacity: 0, scale: 0.7, y: -10 }}
      transition={{ duration: 0.4, type: "spring", stiffness: 200, damping: 20 }}
      className={`relative rounded-lg border-2 px-3 py-2.5 ${
        isDying
          ? "border-zinc-300 bg-zinc-100 dark:border-zinc-600 dark:bg-zinc-800"
          : isBlocking
            ? "border-zinc-300 bg-zinc-100 dark:border-zinc-600 dark:bg-zinc-800"
            : `${colors.border} ${colors.bg}`
      }`}
    >
      {/* PID badge */}
      <div className="absolute -top-2 right-2 rounded bg-zinc-700 px-1.5 py-0 text-[9px] font-mono text-zinc-200 dark:bg-zinc-600">
        PID {agent.pid}
      </div>

      {/* Agent label + type badge */}
      <div className="flex items-center gap-2">
        <span className={`text-sm font-bold ${isDying || isBlocking ? "text-zinc-400 dark:text-zinc-500" : colors.text}`}>
          {agent.label}
        </span>
        {!isLead && agent.type !== "lead" && (
          <span className={`rounded px-1.5 py-0 text-[9px] font-medium ${TYPE_COLORS[agent.type as AgentType].bg} ${TYPE_COLORS[agent.type as AgentType].text}`}>
            {agent.type}
          </span>
        )}
        {agent.spawnMode && (
          <span className={`rounded px-1 py-0 text-[8px] font-mono ${
            agent.spawnMode === "foreground"
              ? "bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400"
              : "bg-zinc-200 text-zinc-600 dark:bg-zinc-700 dark:text-zinc-300"
          }`}>
            {agent.spawnMode === "foreground" ? "FG" : "BG"}
          </span>
        )}
      </div>

      {/* Status indicator */}
      <div className="mt-1 flex items-center gap-1.5">
        <motion.div
          className={`h-2 w-2 rounded-full ${statusIndicator.color}`}
          animate={isWorking ? { opacity: [1, 0.4, 1] } : {}}
          transition={isWorking ? { repeat: Infinity, duration: 1.2 } : {}}
        />
        <span className="text-[10px] text-zinc-500 dark:text-zinc-400">{statusIndicator.label}</span>
        {isCompleted && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="text-xs text-green-500 font-bold"
          >
            &#10003;
          </motion.span>
        )}
      </div>

      {/* Shutdown X overlay */}
      {isDying && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="absolute inset-0 flex items-center justify-center"
        >
          <span className="text-2xl font-bold text-red-400/60">&#10005;</span>
        </motion.div>
      )}
    </motion.div>
  );
}

function BlockingLine() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="mx-6 flex items-center"
    >
      <div className="flex-1 border-t-2 border-dashed border-yellow-400 dark:border-yellow-500" />
      <span className="mx-2 text-[9px] font-mono text-yellow-600 dark:text-yellow-400">awaiting...</span>
      <div className="flex-1 border-t-2 border-dashed border-yellow-400 dark:border-yellow-500" />
    </motion.div>
  );
}

function MessageArrowComponent({ arrow, direction }: { arrow: MessageArrow; direction: "left" | "right" }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: direction === "right" ? -20 : 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.5, type: "spring" }}
      className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-1.5 dark:border-red-800 dark:bg-red-900/20"
    >
      <span className="text-[10px] font-mono text-zinc-500 dark:text-zinc-400">{arrow.from}</span>
      <motion.span
        animate={{ x: [0, 4, 0] }}
        transition={{ repeat: Infinity, duration: 1 }}
        className="text-red-500"
      >
        {direction === "right" ? "\u2192" : "\u2190"}
      </motion.span>
      <span className="text-[10px] font-mono text-zinc-500 dark:text-zinc-400">{arrow.to}</span>
      <span className="text-[9px] text-red-500 dark:text-red-400 font-medium">{arrow.label}</span>
    </motion.div>
  );
}

// --- Main Component ---

export default function ProductionTeams({ title }: { title?: string }) {
  const {
    currentStep, totalSteps, next, prev, reset, isPlaying, toggleAutoPlay,
  } = useSteppedVisualization({ totalSteps: STEPS.length, autoPlayInterval: 3000 });

  const state = useMemo(() => computeStepState(currentStep), [currentStep]);

  const leadAgent = state.agents.find(a => a.id === "lead");
  const workerAgents = state.agents.filter(a => a.id !== "lead");

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
        {title || "Production Agent Teams"}
      </h2>

      <div className="rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-700 dark:bg-zinc-900" style={{ minHeight: 540 }}>
        <div className="flex gap-6" style={{ minHeight: 420 }}>
          {/* Left: Process Boxes */}
          <div className="flex w-[280px] flex-shrink-0 flex-col gap-3">
            {/* Lead agent */}
            <AnimatePresence mode="wait">
              {leadAgent && (
                <ProcessBox key={leadAgent.id} agent={leadAgent} isShutdown={state.shutdownAll} />
              )}
            </AnimatePresence>

            {/* Config + Task Board */}
            <AnimatePresence>
              {state.showConfig && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden"
                >
                  <div className="flex gap-2">
                    <div className="flex-1 rounded border border-zinc-300 bg-zinc-50 px-2 py-1.5 dark:border-zinc-600 dark:bg-zinc-800">
                      <div className="text-[9px] font-mono text-zinc-400">config.json</div>
                      <div className="text-[10px] text-zinc-600 dark:text-zinc-300">maxAgents: 4</div>
                    </div>
                    <div className="flex-1 rounded border border-zinc-300 bg-zinc-50 px-2 py-1.5 dark:border-zinc-600 dark:bg-zinc-800">
                      <div className="text-[9px] font-mono text-zinc-400">task board</div>
                      <div className="text-[10px] text-zinc-600 dark:text-zinc-300">
                        {workerAgents.length > 0 ? `${workerAgents.length} worker(s)` : "empty"}
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Type badges */}
            <AnimatePresence>
              {state.typeBadges.length > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex flex-wrap gap-1.5"
                >
                  {state.typeBadges.map((type, i) => (
                    <motion.div
                      key={type}
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      transition={{ delay: i * 0.1 }}
                    >
                      <TypeBadge type={type} />
                    </motion.div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>

            {/* Blocking line (foreground) */}
            <AnimatePresence>
              {state.blockingLine && <BlockingLine />}
            </AnimatePresence>

            {/* Worker agents */}
            <AnimatePresence>
              {workerAgents.map((agent, i) => (
                <motion.div
                  key={agent.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ delay: i * 0.15 }}
                >
                  <ProcessBox agent={agent} isShutdown={state.shutdownAll} />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>

          {/* Right: Status / Messages */}
          <div className="flex flex-1 flex-col justify-between">
            {/* Step 0: solo info */}
            <AnimatePresence mode="wait">
              {currentStep === 0 && (
                <motion.div
                  key="solo"
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3 dark:border-zinc-700 dark:bg-zinc-800"
                >
                  <div className="text-xs font-bold text-zinc-600 dark:text-zinc-300">Solo Mode</div>
                  <div className="mt-1 text-[11px] text-zinc-500 dark:text-zinc-400">
                    Single process handles everything. No parallelism, no delegation. Good for simple tasks, bottleneck for complex projects.
                  </div>
                </motion.div>
              )}

              {/* Step 1-2: team setup */}
              {currentStep === 1 && (
                <motion.div
                  key="setup"
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="space-y-2"
                >
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-800 dark:bg-red-900/20">
                    <div className="text-xs font-bold text-red-600 dark:text-red-400">Team Initialized</div>
                    <div className="mt-1 text-[11px] text-red-500/80 dark:text-red-400/80">
                      config.json defines max workers, agent types, and permissions. Task board provides shared state for coordination.
                    </div>
                  </div>
                  <div className="rounded border border-zinc-200 bg-zinc-50 p-3 font-mono text-[10px] text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                    <div>{`{`}</div>
                    <div className="pl-3">{`"maxAgents": 4,`}</div>
                    <div className="pl-3">{`"types": ["explore","plan","code","test"],`}</div>
                    <div className="pl-3">{`"taskBoard": "shared"`}</div>
                    <div>{`}`}</div>
                  </div>
                </motion.div>
              )}

              {currentStep === 2 && (
                <motion.div
                  key="types"
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="space-y-3"
                >
                  <div className="text-xs font-bold text-zinc-600 dark:text-zinc-300">Registered Agent Types</div>
                  {(["explore", "plan", "code", "test"] as AgentType[]).map((type, i) => {
                    const c = TYPE_COLORS[type];
                    const descriptions: Record<AgentType, string> = {
                      explore: "Research & information gathering. Read-only tools, web search.",
                      plan: "Architecture & task decomposition. Analyzes codebase structure.",
                      code: "Implementation. Full file read/write + bash access.",
                      test: "Validation. Runs tests, checks output, reports results.",
                    };
                    return (
                      <motion.div
                        key={type}
                        initial={{ opacity: 0, x: 20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.1 }}
                        className={`flex items-start gap-2 rounded-lg border px-3 py-2 ${c.border} ${c.bg}`}
                      >
                        <span className={`mt-0.5 h-2 w-2 flex-shrink-0 rounded-full ${c.dot}`} />
                        <div>
                          <div className={`text-[11px] font-bold ${c.text}`}>{type}</div>
                          <div className="text-[10px] text-zinc-500 dark:text-zinc-400">{descriptions[type]}</div>
                        </div>
                      </motion.div>
                    );
                  })}
                </motion.div>
              )}

              {/* Step 3: foreground spawn info */}
              {currentStep === 3 && (
                <motion.div
                  key="fg-spawn"
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="space-y-3"
                >
                  <div className="rounded-lg border-2 border-purple-300 bg-purple-50 px-4 py-3 dark:border-purple-700 dark:bg-purple-900/20">
                    <div className="text-xs font-bold text-purple-600 dark:text-purple-400">Foreground Mode</div>
                    <div className="mt-1 text-[11px] text-purple-500 dark:text-purple-400/80">
                      Lead spawns researcher and blocks. Like a synchronous function call -- Lead cannot do anything else until researcher returns.
                    </div>
                  </div>
                  <div className="rounded border border-zinc-200 bg-zinc-50 p-3 font-mono text-[10px] dark:border-zinc-700 dark:bg-zinc-800">
                    <div className="text-purple-500">// Lead is blocked</div>
                    <div className="text-zinc-600 dark:text-zinc-300">{`result = await spawn("researcher", {`}</div>
                    <div className="pl-3 text-zinc-600 dark:text-zinc-300">{`type: "explore",`}</div>
                    <div className="pl-3 text-zinc-600 dark:text-zinc-300">{`mode: "foreground"`}</div>
                    <div className="text-zinc-600 dark:text-zinc-300">{`});`}</div>
                  </div>
                </motion.div>
              )}

              {/* Step 4: background spawn */}
              {currentStep === 4 && (
                <motion.div
                  key="bg-spawn"
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="space-y-3"
                >
                  <div className="flex gap-2">
                    <div className="flex-1 rounded-lg border border-green-300 bg-green-50 px-3 py-2 dark:border-green-700 dark:bg-green-900/20">
                      <div className="text-[10px] font-bold text-green-600 dark:text-green-400">researcher returned</div>
                      <div className="text-[9px] text-green-500 dark:text-green-400/80">Lead unblocked, result received</div>
                    </div>
                  </div>
                  <div className="rounded-lg border-2 border-orange-300 bg-orange-50 px-4 py-3 dark:border-orange-700 dark:bg-orange-900/20">
                    <div className="text-xs font-bold text-orange-600 dark:text-orange-400">Background Mode</div>
                    <div className="mt-1 text-[11px] text-orange-500 dark:text-orange-400/80">
                      Two coders spawned in background. Lead stays active -- can continue planning, check progress, or spawn more agents.
                    </div>
                  </div>
                  <div className="rounded border border-zinc-200 bg-zinc-50 p-3 font-mono text-[10px] dark:border-zinc-700 dark:bg-zinc-800">
                    <div className="text-orange-500">// Lead keeps running</div>
                    <div className="text-zinc-600 dark:text-zinc-300">{`spawn("coder-a", { type: "code", mode: "background" });`}</div>
                    <div className="text-zinc-600 dark:text-zinc-300">{`spawn("coder-b", { type: "code", mode: "background" });`}</div>
                  </div>
                </motion.div>
              )}

              {/* Step 5: background running */}
              {currentStep === 5 && (
                <motion.div
                  key="bg-running"
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="space-y-3"
                >
                  <div className="text-xs font-bold text-zinc-600 dark:text-zinc-300">Agent Status</div>
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2 rounded bg-green-50 px-3 py-1.5 dark:bg-green-900/10">
                      <div className="h-2 w-2 rounded-full bg-green-500" />
                      <span className="text-[11px] text-green-700 dark:text-green-300">coder-a: completed &#10003;</span>
                    </div>
                    <div className="flex items-center gap-2 rounded bg-blue-50 px-3 py-1.5 dark:bg-blue-900/10">
                      <motion.div
                        className="h-2 w-2 rounded-full bg-blue-500"
                        animate={{ opacity: [1, 0.4, 1] }}
                        transition={{ repeat: Infinity, duration: 1.2 }}
                      />
                      <span className="text-[11px] text-blue-700 dark:text-blue-300">coder-b: working...</span>
                    </div>
                  </div>

                  {/* Message arrow */}
                  <div className="mt-2">
                    <div className="text-[10px] font-mono text-zinc-400 mb-1">notification</div>
                    {state.messages.map((msg, i) => (
                      <MessageArrowComponent key={i} arrow={msg} direction="left" />
                    ))}
                  </div>

                  {/* Inbox */}
                  <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 dark:border-red-800 dark:bg-red-900/20">
                    <div className="text-[9px] font-mono text-red-400 mb-1">Lead inbox</div>
                    {state.inboxItems.map((item, i) => (
                      <div key={i} className="text-[10px] text-red-600 dark:text-red-400">&#8226; {item}</div>
                    ))}
                  </div>
                </motion.div>
              )}

              {/* Step 6: sendMessage */}
              {currentStep === 6 && (
                <motion.div
                  key="send-msg"
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="space-y-3"
                >
                  <div className="rounded-lg border-2 border-red-300 bg-red-50 px-4 py-3 dark:border-red-700 dark:bg-red-900/20">
                    <div className="text-xs font-bold text-red-600 dark:text-red-400">sendMessage()</div>
                    <div className="mt-1 text-[11px] text-red-500 dark:text-red-400/80">
                      Lead sends a direct message to coder-b with additional context. The agent receives it in its next iteration and adjusts its work.
                    </div>
                  </div>

                  {/* Message arrow */}
                  <div>
                    <div className="text-[10px] font-mono text-zinc-400 mb-1">message delivery</div>
                    {state.messages.map((msg, i) => (
                      <MessageArrowComponent key={i} arrow={msg} direction="right" />
                    ))}
                  </div>

                  <div className="rounded border border-zinc-200 bg-zinc-50 p-3 font-mono text-[10px] dark:border-zinc-700 dark:bg-zinc-800">
                    <div className="text-red-500">// Direct communication</div>
                    <div className="text-zinc-600 dark:text-zinc-300">{`sendMessage("coder-b", {`}</div>
                    <div className="pl-3 text-zinc-600 dark:text-zinc-300">{`content: "Use the new API schema"`}</div>
                    <div className="text-zinc-600 dark:text-zinc-300">{`});`}</div>
                  </div>

                  {/* Final inbox */}
                  <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 dark:border-green-800 dark:bg-green-900/20">
                    <div className="text-[9px] font-mono text-green-500 mb-1">all tasks completed</div>
                    {state.inboxItems.map((item, i) => (
                      <div key={i} className="text-[10px] text-green-600 dark:text-green-400">&#10003; {item}</div>
                    ))}
                  </div>
                </motion.div>
              )}

              {/* Step 7: shutdown */}
              {currentStep === 7 && (
                <motion.div
                  key="shutdown"
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="space-y-3"
                >
                  <motion.div
                    animate={{ opacity: [1, 0.6, 1] }}
                    transition={{ repeat: Infinity, duration: 2 }}
                    className="rounded-lg border-2 border-red-400 bg-red-50 px-4 py-3 dark:border-red-600 dark:bg-red-900/20"
                  >
                    <div className="text-xs font-bold text-red-600 dark:text-red-400">SIGTERM to all agents</div>
                    <div className="mt-1 text-[11px] text-red-500 dark:text-red-400/80">
                      Graceful shutdown: save state, flush outputs, release resources. Team dissolved.
                    </div>
                  </motion.div>

                  <div className="space-y-1.5">
                    {["lead (PID 1000)", "coder-a (PID 1002)", "coder-b (PID 1003)"].map((name, i) => (
                      <motion.div
                        key={name}
                        initial={{ opacity: 1, x: 0 }}
                        animate={{ opacity: 0.4, x: 10 }}
                        transition={{ delay: i * 0.3, duration: 0.6 }}
                        className="flex items-center gap-2 rounded bg-zinc-100 px-3 py-1.5 dark:bg-zinc-800"
                      >
                        <span className="text-red-400 text-xs">&#10005;</span>
                        <span className="text-[11px] text-zinc-500 dark:text-zinc-400 line-through">{name}</span>
                      </motion.div>
                    ))}
                  </div>

                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 1.2 }}
                    className="rounded border border-zinc-300 bg-zinc-50 px-3 py-2 dark:border-zinc-600 dark:bg-zinc-800"
                  >
                    <div className="text-[10px] text-zinc-500 dark:text-zinc-400 font-mono">
                      Team cleanup complete. 3 agents terminated. Resources released.
                    </div>
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        <div className="mt-6">
          <StepControls
            currentStep={currentStep}
            totalSteps={totalSteps}
            onPrev={prev}
            onNext={next}
            onReset={reset}
            isPlaying={isPlaying}
            onToggleAutoPlay={toggleAutoPlay}
            stepTitle={STEPS[currentStep].title}
            stepDescription={STEPS[currentStep].description}
          />
        </div>
      </div>
    </section>
  );
}
