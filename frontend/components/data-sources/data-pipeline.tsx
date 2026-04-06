'use client'

import { useEffect, useRef, useState } from 'react'
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  SkipForward,
  AlertTriangle,
  RefreshCw,
  Download,
  Cpu,
  AlertOctagon,
} from 'lucide-react'
import { getTaskStatus, triggerReprocess } from '@/lib/api-client'
import type { TaskStatus } from '@/lib/api-client'

interface Props {
  taskId: string
  onReset: () => void
}

const POLL_INTERVAL_MS = 3000

// ── Status badge ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: TaskStatus['status'] }) {
  switch (status) {
    case 'SUCCESS':
      return (
        <span className="flex items-center gap-1.5 text-xs font-medium text-green-400 bg-green-400/10 px-2.5 py-1 rounded-full">
          <CheckCircle2 className="w-3.5 h-3.5" /> Completed
        </span>
      )
    case 'FAILURE':
      return (
        <span className="flex items-center gap-1.5 text-xs font-medium text-red-400 bg-red-400/10 px-2.5 py-1 rounded-full">
          <XCircle className="w-3.5 h-3.5" /> Failed
        </span>
      )
    case 'PROGRESS':
    case 'STARTED':
      return (
        <span className="flex items-center gap-1.5 text-xs font-medium text-indigo-400 bg-indigo-400/10 px-2.5 py-1 rounded-full">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Running
        </span>
      )
    case 'RETRY':
      return (
        <span className="flex items-center gap-1.5 text-xs font-medium text-yellow-400 bg-yellow-400/10 px-2.5 py-1 rounded-full">
          <RefreshCw className="w-3.5 h-3.5" /> Retrying
        </span>
      )
    default:
      return (
        <span className="flex items-center gap-1.5 text-xs font-medium text-slate-400 bg-slate-700/50 px-2.5 py-1 rounded-full">
          <Clock className="w-3.5 h-3.5" /> Pending
        </span>
      )
  }
}

// ── Stage timeline ──────────────────────────────────────────────────────────

function StageTimeline({ status }: { status: TaskStatus }) {
  const prog = status.progress
  const result = status.result
  const done = status.status === 'SUCCESS'
  const failed = status.status === 'FAILURE'

  const stage = prog?.stage ?? (done ? 'done' : failed ? 'failed' : 'pending')

  const stages = [
    {
      key: 'fetching',
      label: 'Fetch from Google Maps',
      icon: Download,
      detail:
        stage === 'fetching'
          ? 'Calling SerpAPI…'
          : prog || done
            ? `${(result ?? prog)?.total ?? prog?.total ?? 0} reviews found`
            : null,
    },
    {
      key: 'processing',
      label: 'Sentiment + Embedding',
      icon: Cpu,
      detail:
        stage === 'processing' && prog
          ? `Processing review ${prog.processed + prog.skipped + 1} of ${prog.total}`
          : done
            ? `${result?.processed ?? 0} processed, ${result?.skipped ?? 0} skipped`
            : null,
    },
    {
      key: 'rate_limited',
      label: 'Rate limit hit',
      icon: AlertOctagon,
      detail:
        stage === 'rate_limited' && prog
          ? `Stopped at ${prog.processed}/${prog.total} — ${prog.total - prog.processed - prog.skipped} reviews stranded`
          : null,
      isWarning: true,
      hidden: stage !== 'rate_limited' && !(done && (result?.rate_limited ?? 0) > 0),
    },
  ]

  function stageStatus(key: string): 'done' | 'active' | 'pending' | 'warning' {
    if (failed) return key === 'fetching' ? 'active' : 'pending'
    if (key === 'rate_limited') {
      if (stage === 'rate_limited') return 'warning'
      if (done && (result?.rate_limited ?? 0) > 0) return 'warning'
      return 'pending'
    }
    const order = ['fetching', 'processing', 'done']
    const current = done ? 'done' : stage
    return order.indexOf(key) < order.indexOf(current)
      ? 'done'
      : order.indexOf(key) === order.indexOf(current)
        ? 'active'
        : 'pending'
  }

  return (
    <div className="space-y-3">
      {stages
        .filter((s) => !s.hidden)
        .map((s) => {
          const Icon = s.icon
          const st = stageStatus(s.key)
          return (
            <div key={s.key} className="flex items-start gap-3">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${
                  st === 'done'
                    ? 'bg-green-400/15 text-green-400'
                    : st === 'active'
                      ? 'bg-indigo-400/15 text-indigo-400'
                      : st === 'warning'
                        ? 'bg-yellow-400/15 text-yellow-400'
                        : 'bg-slate-800 text-slate-600'
                }`}
              >
                {st === 'active' ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : st === 'done' ? (
                  <CheckCircle2 className="w-3.5 h-3.5" />
                ) : (
                  <Icon className="w-3.5 h-3.5" />
                )}
              </div>
              <div className="min-w-0">
                <p
                  className={`text-xs font-medium ${
                    st === 'pending' ? 'text-slate-500' : 'text-slate-200'
                  }`}
                >
                  {s.label}
                </p>
                {s.detail && (
                  <p
                    className={`text-xs mt-0.5 ${
                      st === 'warning' ? 'text-yellow-400/80' : 'text-slate-400'
                    }`}
                  >
                    {s.detail}
                  </p>
                )}
              </div>
            </div>
          )
        })}
    </div>
  )
}

// ── Progress bar ────────────────────────────────────────────────────────────

function ProgressBar({ status }: { status: TaskStatus }) {
  const prog = status.progress
  if (!prog || prog.total === 0) {
    return (
      <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
        <div className="h-full w-1/3 rounded-full bg-indigo-500 animate-pulse" />
      </div>
    )
  }
  const done = prog.processed + prog.skipped
  const pct = Math.round((done / prog.total) * 100)
  return (
    <div className="space-y-1">
      <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
        <div
          className="h-full rounded-full bg-indigo-500 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-slate-500 text-right">{pct}%</p>
    </div>
  )
}

// ── Main component ──────────────────────────────────────────────────────────

export function DataPipeline({ taskId, onReset }: Props) {
  const [status, setStatus] = useState<TaskStatus | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
  const [reprocessTaskId, setReprocessTaskId] = useState<string | null>(null)
  const [reprocessing, setReprocessing] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopPolling() {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }

  async function poll() {
    try {
      const data = await getTaskStatus(taskId)
      setStatus(data)
      setPollError(null)
      if (data.status === 'SUCCESS' || data.status === 'FAILURE' || data.status === 'REVOKED') {
        stopPolling()
      }
    } catch (err) {
      setPollError(err instanceof Error ? err.message : 'Failed to fetch task status')
    }
  }

  useEffect(() => {
    poll()
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS)
    return stopPolling
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId])

  async function handleReprocess() {
    setReprocessing(true)
    try {
      const { task_id } = await triggerReprocess()
      setReprocessTaskId(task_id)
    } catch {
      // ignore — user can retry
    } finally {
      setReprocessing(false)
    }
  }

  const isTerminal =
    status?.status === 'SUCCESS' ||
    status?.status === 'FAILURE' ||
    status?.status === 'REVOKED'

  const hasRateLimited =
    (status?.progress?.stage === 'rate_limited') ||
    (status?.status === 'SUCCESS' && (status.result?.rate_limited ?? 0) > 0)

  const isRunning = !isTerminal && status !== null

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-6 shadow-soft space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Ingestion Job</h2>
          <p className="text-xs text-slate-500 font-mono mt-0.5 truncate max-w-xs">{taskId}</p>
        </div>
        {status && <StatusBadge status={status.status} />}
      </div>

      {/* Poll error */}
      {pollError && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-yellow-400 text-xs">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{pollError}</span>
        </div>
      )}

      {/* Stage timeline */}
      {status && <StageTimeline status={status} />}

      {/* Progress bar — only while running */}
      {isRunning && <ProgressBar status={status} />}

      {/* Result stats */}
      {status?.status === 'SUCCESS' && status.result && (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg bg-slate-800/60 border border-slate-700/50 p-4 text-center">
            <p className="text-2xl font-bold text-green-400">{status.result.processed}</p>
            <p className="text-xs text-slate-400 mt-1">Processed</p>
          </div>
          <div className="rounded-lg bg-slate-800/60 border border-slate-700/50 p-4 text-center">
            <p className="text-2xl font-bold text-slate-300">{status.result.skipped}</p>
            <div className="flex items-center justify-center gap-1 mt-1">
              <SkipForward className="w-3 h-3 text-slate-500" />
              <p className="text-xs text-slate-400">Skipped</p>
            </div>
          </div>
          <div className="rounded-lg bg-slate-800/60 border border-slate-700/50 p-4 text-center">
            <p className="text-2xl font-bold text-yellow-400">{status.result.rate_limited}</p>
            <p className="text-xs text-slate-400 mt-1">Rate limited</p>
          </div>
        </div>
      )}

      {/* Failure error */}
      {status?.status === 'FAILURE' && status.error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
          <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="font-mono">{status.error}</span>
        </div>
      )}

      {/* Rate-limit recovery */}
      {hasRateLimited && (
        <div className="p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20 space-y-2">
          <p className="text-xs text-yellow-300 font-medium">
            Some reviews weren&apos;t fully processed due to the LLM rate limit.
            They are saved in the DB — click below to resume processing.
          </p>
          {reprocessTaskId ? (
            <p className="text-xs text-green-400">
              Reprocess job queued — task ID: <span className="font-mono">{reprocessTaskId}</span>
            </p>
          ) : (
            <button
              onClick={handleReprocess}
              disabled={reprocessing}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-yellow-500/20 hover:bg-yellow-500/30 text-yellow-300 text-xs font-medium transition-colors disabled:opacity-50"
            >
              {reprocessing ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
              Resume processing stranded reviews
            </button>
          )}
        </div>
      )}

      {/* Reset */}
      {isTerminal && (
        <button
          onClick={onReset}
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 text-sm font-medium transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Run another ingestion
        </button>
      )}
    </div>
  )
}
