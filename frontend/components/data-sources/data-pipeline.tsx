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
} from 'lucide-react'
import { getTaskStatus } from '@/lib/api-client'
import type { TaskStatus } from '@/lib/api-client'

interface Props {
  taskId: string
  onReset: () => void
}

const POLL_INTERVAL_MS = 3000

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

export function DataPipeline({ taskId, onReset }: Props) {
  const [status, setStatus] = useState<TaskStatus | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
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

  const isTerminal =
    status?.status === 'SUCCESS' ||
    status?.status === 'FAILURE' ||
    status?.status === 'REVOKED'

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

      {/* Polling error */}
      {pollError && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-yellow-400 text-xs">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{pollError}</span>
        </div>
      )}

      {/* Live progress indicator */}
      {!isTerminal && !pollError && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-400" />
            Scraping reviews and running sentiment analysis…
          </div>
          <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
            <div className="h-full w-1/3 rounded-full bg-indigo-500 animate-pulse" />
          </div>
          <p className="text-xs text-slate-500">Polling every {POLL_INTERVAL_MS / 1000}s</p>
        </div>
      )}

      {/* Success result */}
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

      {/* Success notes */}
      {status?.status === 'SUCCESS' && (
        <div className="text-xs text-slate-400 leading-relaxed">
          {status.result?.rate_limited && status.result.rate_limited > 0 ? (
            <p className="text-yellow-400/80">
              Some reviews hit the LLM rate limit. Go to the{' '}
              <span className="text-yellow-300">AI Chat</span> page to query existing data, or re-run
              ingestion to finish processing the remaining reviews.
            </p>
          ) : (
            <p className="text-green-400/80">
              All reviews scraped, cleaned, sentiment-analysed, and embedded. Head to{' '}
              <span className="text-green-300">AI Chat</span> to start querying them.
            </p>
          )}
        </div>
      )}

      {/* Failure error */}
      {status?.status === 'FAILURE' && status.error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
          <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="font-mono">{status.error}</span>
        </div>
      )}

      {/* Reset button */}
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
