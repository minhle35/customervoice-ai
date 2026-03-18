import clsx from 'clsx'
import type { ReactNode } from 'react'

interface MetricCardProps {
  title: string
  value: string | number
  change?: string
  changeType?: 'positive' | 'negative' | 'neutral'
  description?: string
  icon: ReactNode
  iconBg?: string
}

export function MetricCard({
  title,
  value,
  change,
  changeType = 'neutral',
  description,
  icon,
  iconBg = 'bg-indigo-600/20',
}: MetricCardProps) {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 shadow-soft flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div className={clsx('w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0', iconBg)}>
          {icon}
        </div>
        {change !== undefined && (
          <span
            className={clsx(
              'text-xs font-medium px-2 py-0.5 rounded-full',
              changeType === 'positive' && 'text-green-400 bg-green-400/10',
              changeType === 'negative' && 'text-red-400 bg-red-400/10',
              changeType === 'neutral' && 'text-slate-400 bg-slate-700/50'
            )}
          >
            {change}
          </span>
        )}
      </div>
      <div>
        <p className="text-2xl font-bold text-slate-100">{value}</p>
        <p className="text-sm text-slate-400 mt-0.5">{title}</p>
        {description && (
          <p className="text-xs text-slate-500 mt-1">{description}</p>
        )}
      </div>
    </div>
  )
}
