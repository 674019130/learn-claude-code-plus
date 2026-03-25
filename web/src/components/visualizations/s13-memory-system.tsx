"use client";

import { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useSteppedVisualization } from "@/hooks/useSteppedVisualization";
import { StepControls } from "@/components/visualizations/shared/step-controls";

interface MemoryFile {
  id: string;
  name: string;
  indent: number;
  isDir: boolean;
  highlighted?: boolean;
  highlightColor?: string;
  content?: string;
}

interface SessionBlock {
  id: string;
  label: string;
  active: boolean;
  closed: boolean;
  actions: string[];
}

interface StepState {
  files: MemoryFile[];
  sessions: SessionBlock[];
  annotation: string | null;
}

function computeStepState(step: number): StepState {
  switch (step) {
    case 0:
      return {
        files: [
          { id: "dir-memory", name: ".memory/", indent: 0, isDir: true },
          { id: "f-index", name: "MEMORY.md", indent: 1, isDir: false, content: "(empty)" },
        ],
        sessions: [],
        annotation: null,
      };

    case 1:
      return {
        files: [
          { id: "dir-memory", name: ".memory/", indent: 0, isDir: true },
          { id: "f-index", name: "MEMORY.md", indent: 1, isDir: false, content: "(empty)" },
        ],
        sessions: [
          {
            id: "s1",
            label: "Session 1",
            active: true,
            closed: false,
            actions: ["User: \"Build an auth module\"", "Agent reads codebase..."],
          },
        ],
        annotation: null,
      };

    case 2:
      return {
        files: [
          { id: "dir-memory", name: ".memory/", indent: 0, isDir: true },
          {
            id: "f-index",
            name: "MEMORY.md",
            indent: 1,
            isDir: false,
            content: "# Index\n- project_auth.md\n- user_prefs.md",
          },
          {
            id: "f-auth",
            name: "project_auth.md",
            indent: 1,
            isDir: false,
            highlighted: true,
            highlightColor: "border-purple-400 bg-purple-50 dark:border-purple-600 dark:bg-purple-900/30",
            content: "Auth: JWT + OAuth2\nStack: Next.js + Supabase",
          },
          {
            id: "f-prefs",
            name: "user_prefs.md",
            indent: 1,
            isDir: false,
            highlighted: true,
            highlightColor: "border-purple-400 bg-purple-50 dark:border-purple-600 dark:bg-purple-900/30",
            content: "Prefers TypeScript\nTest framework: vitest",
          },
        ],
        sessions: [
          {
            id: "s1",
            label: "Session 1",
            active: true,
            closed: false,
            actions: [
              "User: \"Build an auth module\"",
              "Agent reads codebase...",
              "Agent saves to .memory/",
            ],
          },
        ],
        annotation: "Agent persists knowledge to memory files",
      };

    case 3:
      return {
        files: [
          { id: "dir-memory", name: ".memory/", indent: 0, isDir: true },
          {
            id: "f-index",
            name: "MEMORY.md",
            indent: 1,
            isDir: false,
            highlighted: true,
            highlightColor: "border-emerald-400 bg-emerald-50 dark:border-emerald-600 dark:bg-emerald-900/30",
            content: "# Index\n- project_auth.md\n- user_prefs.md",
          },
          {
            id: "f-auth",
            name: "project_auth.md",
            indent: 1,
            isDir: false,
            highlighted: true,
            highlightColor: "border-emerald-400 bg-emerald-50 dark:border-emerald-600 dark:bg-emerald-900/30",
          },
          {
            id: "f-prefs",
            name: "user_prefs.md",
            indent: 1,
            isDir: false,
            highlighted: true,
            highlightColor: "border-emerald-400 bg-emerald-50 dark:border-emerald-600 dark:bg-emerald-900/30",
          },
        ],
        sessions: [
          {
            id: "s1",
            label: "Session 1",
            active: false,
            closed: true,
            actions: ["Session ended", "Context window cleared"],
          },
        ],
        annotation: "Session ends -- but memory files persist on disk",
      };

    case 4:
      return {
        files: [
          { id: "dir-memory", name: ".memory/", indent: 0, isDir: true },
          {
            id: "f-index",
            name: "MEMORY.md",
            indent: 1,
            isDir: false,
            highlighted: true,
            highlightColor: "border-violet-500 bg-violet-50 dark:border-violet-500 dark:bg-violet-900/30",
            content: "# Index\n- project_auth.md\n- user_prefs.md",
          },
          { id: "f-auth", name: "project_auth.md", indent: 1, isDir: false },
          { id: "f-prefs", name: "user_prefs.md", indent: 1, isDir: false },
        ],
        sessions: [
          {
            id: "s1",
            label: "Session 1",
            active: false,
            closed: true,
            actions: ["(completed)"],
          },
          {
            id: "s2",
            label: "Session 2",
            active: true,
            closed: false,
            actions: ["Agent starts fresh", "Reads MEMORY.md index"],
          },
        ],
        annotation: "New session reads the index to discover available memories",
      };

    case 5:
      return {
        files: [
          { id: "dir-memory", name: ".memory/", indent: 0, isDir: true },
          {
            id: "f-index",
            name: "MEMORY.md",
            indent: 1,
            isDir: false,
            content: "# Index\n- project_auth.md\n- user_prefs.md",
          },
          {
            id: "f-auth",
            name: "project_auth.md",
            indent: 1,
            isDir: false,
            highlighted: true,
            highlightColor: "border-violet-500 bg-violet-50 dark:border-violet-500 dark:bg-violet-900/30",
            content: "Auth: JWT + OAuth2\nStack: Next.js + Supabase",
          },
          { id: "f-prefs", name: "user_prefs.md", indent: 1, isDir: false },
        ],
        sessions: [
          {
            id: "s1",
            label: "Session 1",
            active: false,
            closed: true,
            actions: ["(completed)"],
          },
          {
            id: "s2",
            label: "Session 2",
            active: true,
            closed: false,
            actions: [
              "Agent starts fresh",
              "Reads MEMORY.md index",
              "Loads project_auth.md on demand",
            ],
          },
        ],
        annotation: "Agent loads only the detail files it needs -- not everything at once",
      };

    case 6:
      return {
        files: [
          { id: "dir-memory", name: ".memory/", indent: 0, isDir: true },
          {
            id: "f-index",
            name: "MEMORY.md",
            indent: 1,
            isDir: false,
            content: "# Index\n- project_auth.md\n- user_prefs.md",
          },
          {
            id: "f-auth",
            name: "project_auth.md",
            indent: 1,
            isDir: false,
            highlighted: true,
            highlightColor: "border-amber-400 bg-amber-50 dark:border-amber-600 dark:bg-amber-900/30",
            content: "Auth: JWT + OAuth2 + RBAC\nStatus: login done, roles WIP",
          },
          { id: "f-prefs", name: "user_prefs.md", indent: 1, isDir: false },
        ],
        sessions: [
          {
            id: "s1",
            label: "Session 1",
            active: false,
            closed: true,
            actions: ["(completed)"],
          },
          {
            id: "s2",
            label: "Session 2",
            active: true,
            closed: false,
            actions: [
              "Agent starts fresh",
              "Reads MEMORY.md index",
              "Loads project_auth.md",
              "Updates with new progress",
            ],
          },
        ],
        annotation: "Agent writes updated knowledge back to the memory file",
      };

    case 7:
      return {
        files: [
          { id: "dir-memory", name: ".memory/", indent: 0, isDir: true },
          {
            id: "f-index",
            name: "MEMORY.md",
            indent: 1,
            isDir: false,
            content: "# Index\n- project_auth.md\n- user_prefs.md\n- api_design.md\n- deploy_notes.md\n- db_schema.md",
          },
          { id: "f-auth", name: "project_auth.md", indent: 1, isDir: false },
          { id: "f-prefs", name: "user_prefs.md", indent: 1, isDir: false },
          { id: "f-api", name: "api_design.md", indent: 1, isDir: false },
          { id: "f-deploy", name: "deploy_notes.md", indent: 1, isDir: false },
          { id: "f-db", name: "db_schema.md", indent: 1, isDir: false },
        ],
        sessions: [
          {
            id: "s1",
            label: "Session 1",
            active: false,
            closed: true,
            actions: ["(completed)"],
          },
          {
            id: "s2",
            label: "Session 2",
            active: false,
            closed: true,
            actions: ["(completed)"],
          },
          {
            id: "s3",
            label: "Session 3",
            active: false,
            closed: true,
            actions: ["(completed)"],
          },
          {
            id: "s4",
            label: "Session 4",
            active: true,
            closed: false,
            actions: ["Knowledge accumulates", "Each session builds on the last"],
          },
        ],
        annotation: "Memory grows across sessions -- the agent builds lasting project knowledge",
      };

    default:
      return { files: [], sessions: [], annotation: null };
  }
}

const STEPS = [
  {
    title: "Empty Memory",
    description:
      "The .memory/ directory starts with only an empty MEMORY.md index file. No knowledge persists yet.",
  },
  {
    title: "Session 1 Starts",
    description:
      "A new session begins. The user asks the agent to build an auth module. The agent starts working.",
  },
  {
    title: "Save to Memory",
    description:
      "The agent saves what it learned -- project architecture and user preferences -- into memory files.",
  },
  {
    title: "Session 1 Ends",
    description:
      "The session ends and the context window is cleared. But the memory files persist on disk.",
  },
  {
    title: "Session 2 Starts",
    description:
      "A brand new session. The agent reads the MEMORY.md index to discover what knowledge is available.",
  },
  {
    title: "Load on Demand",
    description:
      "The agent reads only the detail file it needs (project_auth.md), not every memory file at once.",
  },
  {
    title: "Update Memory",
    description:
      "After making progress, the agent updates the memory file with new information and status.",
  },
  {
    title: "Knowledge Grows",
    description:
      "Over multiple sessions, memory files accumulate. The agent builds lasting project knowledge.",
  },
];

function FileTree({ files }: { files: MemoryFile[] }) {
  return (
    <div className="space-y-1">
      <AnimatePresence mode="popLayout">
        {files.map((file) => (
          <motion.div
            key={file.id}
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            transition={{ duration: 0.35 }}
            style={{ paddingLeft: file.indent * 20 }}
          >
            <div
              className={`flex items-start gap-2 rounded-md px-2 py-1.5 font-mono text-xs transition-colors ${
                file.highlighted && file.highlightColor
                  ? `border ${file.highlightColor}`
                  : "border border-transparent"
              }`}
            >
              <span className="flex-shrink-0 select-none">
                {file.isDir ? "📁" : "📄"}
              </span>
              <div className="min-w-0 flex-1">
                <div
                  className={`font-semibold ${
                    file.isDir
                      ? "text-violet-600 dark:text-violet-400"
                      : "text-zinc-700 dark:text-zinc-300"
                  }`}
                >
                  {file.name}
                </div>
                <AnimatePresence>
                  {file.content && (
                    <motion.pre
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.3 }}
                      className="mt-1 overflow-hidden whitespace-pre-wrap text-[10px] leading-relaxed text-zinc-500 dark:text-zinc-400"
                    >
                      {file.content}
                    </motion.pre>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

function SessionTimeline({ sessions }: { sessions: SessionBlock[] }) {
  return (
    <div className="space-y-3">
      <AnimatePresence mode="popLayout">
        {sessions.map((session) => (
          <motion.div
            key={session.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.35 }}
            className={`rounded-lg border-2 px-3 py-2.5 ${
              session.active
                ? "border-violet-400 bg-violet-50 dark:border-violet-500 dark:bg-violet-900/20"
                : session.closed
                  ? "border-zinc-200 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800/50"
                  : "border-zinc-300 bg-white dark:border-zinc-600 dark:bg-zinc-900"
            }`}
          >
            <div className="mb-1.5 flex items-center gap-2">
              <div
                className={`h-2 w-2 rounded-full ${
                  session.active
                    ? "bg-violet-500 shadow-[0_0_6px_rgba(139,92,246,0.5)]"
                    : "bg-zinc-400 dark:bg-zinc-500"
                }`}
              />
              <span
                className={`text-xs font-bold ${
                  session.active
                    ? "text-violet-700 dark:text-violet-300"
                    : "text-zinc-500 dark:text-zinc-400"
                }`}
              >
                {session.label}
              </span>
              {session.closed && !session.active && (
                <span className="ml-auto text-[10px] text-zinc-400 dark:text-zinc-500">
                  closed
                </span>
              )}
              {session.active && (
                <span className="ml-auto text-[10px] font-medium text-violet-500 dark:text-violet-400">
                  active
                </span>
              )}
            </div>
            <div className="space-y-0.5">
              {session.actions.map((action, i) => (
                <motion.div
                  key={`${session.id}-a-${i}`}
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.1, duration: 0.25 }}
                  className={`text-[11px] ${
                    session.active
                      ? "text-violet-600 dark:text-violet-300"
                      : "text-zinc-400 dark:text-zinc-500"
                  }`}
                >
                  {action}
                </motion.div>
              ))}
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

export default function MemorySystem({ title }: { title?: string }) {
  const {
    currentStep,
    totalSteps,
    next,
    prev,
    reset,
    isPlaying,
    toggleAutoPlay,
  } = useSteppedVisualization({ totalSteps: STEPS.length, autoPlayInterval: 2500 });

  const state = useMemo(() => computeStepState(currentStep), [currentStep]);

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
        {title || "Memory System"}
      </h2>

      <div
        className="rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-700 dark:bg-zinc-900"
        style={{ minHeight: 500 }}
      >
        <div className="flex gap-6">
          {/* Left side: File System Tree */}
          <div className="w-[280px] flex-shrink-0">
            <div className="mb-3 flex items-center gap-2">
              <div className="h-3 w-3 rounded bg-violet-500" />
              <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">
                File System
              </span>
            </div>
            <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-800/50">
              <FileTree files={state.files} />
            </div>

            {/* Annotation callout */}
            <AnimatePresence>
              {state.annotation && (
                <motion.div
                  key={state.annotation}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 8 }}
                  transition={{ duration: 0.35 }}
                  className="mt-3 rounded-md border border-violet-300 bg-violet-50 px-3 py-2 dark:border-violet-700 dark:bg-violet-900/20"
                >
                  <div className="text-[11px] leading-relaxed text-violet-700 dark:text-violet-300">
                    {state.annotation}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Right side: Session Timeline */}
          <div className="flex-1">
            <div className="mb-3 flex items-center gap-2">
              <div className="h-3 w-3 rounded bg-zinc-400 dark:bg-zinc-500" />
              <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">
                Session Timeline
              </span>
            </div>
            <div className="min-h-[280px]">
              {state.sessions.length > 0 ? (
                <SessionTimeline sessions={state.sessions} />
              ) : (
                <div className="flex h-[280px] items-center justify-center rounded-lg border-2 border-dashed border-zinc-200 dark:border-zinc-700">
                  <span className="text-xs text-zinc-400 dark:text-zinc-500">
                    No sessions yet
                  </span>
                </div>
              )}
            </div>

            {/* Legend */}
            <div className="mt-4 flex items-center gap-4">
              <div className="flex items-center gap-1.5">
                <div className="h-2.5 w-2.5 rounded-full bg-violet-500 shadow-[0_0_6px_rgba(139,92,246,0.5)]" />
                <span className="text-[10px] text-zinc-500 dark:text-zinc-400">
                  active session
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="h-2.5 w-2.5 rounded-full bg-zinc-400" />
                <span className="text-[10px] text-zinc-500 dark:text-zinc-400">
                  closed session
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px]">📄</span>
                <span className="text-[10px] text-zinc-500 dark:text-zinc-400">
                  memory file
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Step Controls */}
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
