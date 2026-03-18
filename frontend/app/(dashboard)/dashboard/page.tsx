'use client'

import { useState } from 'react'
import { BarChart2, MessageSquare, TrendingUp, TrendingDown, Globe } from 'lucide-react'
import { TopNav } from '@/components/ui/TopNav'
import { MetricCard } from '@/components/dashboard/MetricCard'
import { ReviewsTable } from '@/components/tables/ReviewsTable'
import { useReviews } from '@/hooks/useReviews'
import type { Platform } from '@/types'

const PLATFORMS: { label: string; value: string }[] = [
  { label: 'All Platforms', value: '' },
  { label: 'Google', value: 'google' },
  { label: 'Reddit', value: 'reddit' },
  { label: 'Facebook', value: 'facebook' },
]

const SENTIMENTS = [
  { label: 'All Sentiments', value: '' },
  { label: 'Positive', value: 'positive' },
  { label: 'Neutral', value: 'neutral' },
  { label: 'Negative', value: 'negative' },
]

export default function DashboardPage() {
  const [platform, setPlatform] = useState('')
  const [sentiment, setSentiment] = useState('')

  const { data, isLoading } = useReviews({
    platform: platform || undefined,
    limit: 20,
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0

  const positiveCount = items.filter((r) => r.sentiment_label === 'positive').length
  const negativeCount = items.filter((r) => r.sentiment_label === 'negative').length
  const positivePct = items.length > 0 ? Math.round((positiveCount / items.length) * 100) : 0
  const negativePct = items.length > 0 ? Math.round((negativeCount / items.length) * 100) : 0

  const filteredReviews = sentiment
    ? items.filter((r) => r.sentiment_label === sentiment)
    : items

  return (
    <div className="min-h-full">
      <TopNav title="Dashboard" subtitle="Overview of your customer feedback" />

      <div className="p-6 space-y-6">
        {/* Metric cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          <MetricCard
            title="Total Reviews"
            value={total}
            change="+12%"
            changeType="positive"
            description="Across all platforms"
            icon={<MessageSquare className="w-5 h-5 text-indigo-400" />}
            iconBg="bg-indigo-600/20"
          />
          <MetricCard
            title="Positive Sentiment"
            value={`${positivePct}%`}
            change="+3%"
            changeType="positive"
            description="Of reviewed items"
            icon={<TrendingUp className="w-5 h-5 text-green-400" />}
            iconBg="bg-green-600/20"
          />
          <MetricCard
            title="Negative Sentiment"
            value={`${negativePct}%`}
            change="-1%"
            changeType="positive"
            description="Needs attention"
            icon={<TrendingDown className="w-5 h-5 text-red-400" />}
            iconBg="bg-red-600/20"
          />
          <MetricCard
            title="Platforms Monitored"
            value={3}
            changeType="neutral"
            description="Google, Reddit, Facebook"
            icon={<Globe className="w-5 h-5 text-cyan-400" />}
            iconBg="bg-cyan-600/20"
          />
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {/* Sentiment trend */}
          <div className="xl:col-span-2 rounded-xl bg-slate-900 border border-slate-800 p-5 shadow-soft">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-slate-200">Sentiment Trend</h2>
                <p className="text-xs text-slate-500 mt-0.5">Last 30 days</p>
              </div>
              <BarChart2 className="w-4 h-4 text-slate-500" />
            </div>
            <svg viewBox="0 0 600 160" className="w-full" preserveAspectRatio="none">
              <defs>
                <linearGradient id="posGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity="0.3" />
                  <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
                </linearGradient>
                <linearGradient id="negGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ef4444" stopOpacity="0.3" />
                  <stop offset="100%" stopColor="#ef4444" stopOpacity="0" />
                </linearGradient>
              </defs>
              {/* Grid lines */}
              {[0, 40, 80, 120, 160].map((y) => (
                <line key={y} x1="0" y1={y} x2="600" y2={y} stroke="#1e293b" strokeWidth="1" />
              ))}
              {/* Positive area */}
              <polyline
                fill="url(#posGrad)"
                stroke="none"
                points="0,120 60,100 120,90 180,70 240,80 300,60 360,50 420,65 480,45 540,55 600,40 600,160 0,160"
              />
              <polyline
                fill="none"
                stroke="#10b981"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                points="0,120 60,100 120,90 180,70 240,80 300,60 360,50 420,65 480,45 540,55 600,40"
              />
              {/* Negative area */}
              <polyline
                fill="url(#negGrad)"
                stroke="none"
                points="0,140 60,135 120,138 180,130 240,132 300,125 360,128 420,122 480,118 540,120 600,115 600,160 0,160"
              />
              <polyline
                fill="none"
                stroke="#ef4444"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                points="0,140 60,135 120,138 180,130 240,132 300,125 360,128 420,122 480,118 540,120 600,115"
              />
            </svg>
            <div className="flex items-center gap-4 mt-3">
              <span className="flex items-center gap-1.5 text-xs text-slate-400">
                <span className="w-3 h-0.5 bg-green-400 inline-block rounded" /> Positive
              </span>
              <span className="flex items-center gap-1.5 text-xs text-slate-400">
                <span className="w-3 h-0.5 bg-red-400 inline-block rounded" /> Negative
              </span>
            </div>
          </div>

          {/* Platform donut */}
          <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 shadow-soft">
            <div className="mb-4">
              <h2 className="text-sm font-semibold text-slate-200">Platform Split</h2>
              <p className="text-xs text-slate-500 mt-0.5">By review volume</p>
            </div>
            <div className="flex items-center justify-center">
              <svg viewBox="0 0 120 120" className="w-32 h-32">
                {/* Donut segments: Google 45%, Reddit 35%, Facebook 20% */}
                <circle cx="60" cy="60" r="45" fill="none" stroke="#1e293b" strokeWidth="18" />
                <circle
                  cx="60" cy="60" r="45" fill="none"
                  stroke="#6366f1" strokeWidth="18"
                  strokeDasharray="127 155"
                  strokeDashoffset="0"
                  transform="rotate(-90 60 60)"
                />
                <circle
                  cx="60" cy="60" r="45" fill="none"
                  stroke="#06b6d4" strokeWidth="18"
                  strokeDasharray="99 183"
                  strokeDashoffset="-127"
                  transform="rotate(-90 60 60)"
                />
                <circle
                  cx="60" cy="60" r="45" fill="none"
                  stroke="#8b5cf6" strokeWidth="18"
                  strokeDasharray="56 226"
                  strokeDashoffset="-226"
                  transform="rotate(-90 60 60)"
                />
              </svg>
            </div>
            <div className="space-y-2 mt-3">
              {[
                { label: 'Google', pct: '45%', color: 'bg-indigoCV' },
                { label: 'Reddit', pct: '35%', color: 'bg-cyanCV' },
                { label: 'Facebook', pct: '20%', color: 'bg-violet-500' },
              ].map(({ label, pct, color }) => (
                <div key={label} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2 text-slate-400">
                    <span className={`w-2 h-2 rounded-full ${color}`} />
                    {label}
                  </span>
                  <span className="text-slate-300 font-medium">{pct}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Review volume bar chart */}
        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 shadow-soft">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-slate-200">Review Volume</h2>
              <p className="text-xs text-slate-500 mt-0.5">Daily reviews, last 14 days</p>
            </div>
          </div>
          <div className="flex items-end gap-2 h-24">
            {[18, 32, 25, 41, 38, 29, 45, 52, 34, 47, 39, 55, 43, 60].map((h, i) => (
              <div key={i} className="flex-1 flex flex-col items-center gap-1">
                <div
                  className="w-full rounded-t bg-indigo-600/60 hover:bg-indigo-500/70 transition-colors"
                  style={{ height: `${(h / 60) * 80}px` }}
                />
              </div>
            ))}
          </div>
        </div>

        {/* Reviews table with filters */}
        <div className="space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <h2 className="text-sm font-semibold text-slate-200">Recent Reviews</h2>
            <div className="flex items-center gap-2">
              <select
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                className="text-xs rounded-lg bg-slate-800 border border-slate-700 text-slate-300 px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                {PLATFORMS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
              <select
                value={sentiment}
                onChange={(e) => setSentiment(e.target.value)}
                className="text-xs rounded-lg bg-slate-800 border border-slate-700 text-slate-300 px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                {SENTIMENTS.map((s) => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
          </div>
          <ReviewsTable reviews={filteredReviews} isLoading={isLoading} />
        </div>
      </div>
    </div>
  )
}
