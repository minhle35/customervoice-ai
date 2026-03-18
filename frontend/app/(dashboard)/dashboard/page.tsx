'use client'

import { useState } from 'react'
import { BarChart2, MessageSquare, TrendingUp, TrendingDown, Star, Sparkles, Tag } from 'lucide-react'
import { TopNav } from '@/components/ui/TopNav'
import { MetricCard } from '@/components/dashboard/MetricCard'
import { ReviewsTable } from '@/components/tables/ReviewsTable'
import { useReviews } from '@/hooks/useReviews'
import type { Review } from '@/types'

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

// Placeholder data shown when API returns no reviews
const MOCK_REVIEWS: Review[] = [
  {
    id: 'mock-1',
    platform: 'google',
    platform_id: 'mock-1',
    business_id: 'demo',
    business_name: 'Bien Vinh Hao 2 Seafood Restaurant',
    author: 'James Mitchell',
    rating: 5,
    content: 'Incredibly fresh seafood and stunning ocean views. Staff were attentive and professional throughout. Will definitely be coming back!',
    sentiment_score: 0.92,
    sentiment_label: 'positive',
    topics: ['fresh seafood', 'ocean view', 'service quality'],
    is_processed: true,
    published_at: '2026-03-15T10:22:00Z',
    created_at: '2026-03-15T10:22:00Z',
  },
  {
    id: 'mock-2',
    platform: 'google',
    platform_id: 'mock-2',
    business_id: 'demo',
    business_name: 'Bien Vinh Hao 2 Seafood Restaurant',
    author: 'Sarah Thompson',
    rating: 4,
    content: 'Spacious and airy restaurant with great food. Service was a bit slow on the weekend but overall a pleasant experience. Reasonable prices for the quality.',
    sentiment_score: 0.65,
    sentiment_label: 'positive',
    topics: ['ambiance', 'wait time', 'pricing'],
    is_processed: true,
    published_at: '2026-03-14T14:05:00Z',
    created_at: '2026-03-14T14:05:00Z',
  },
  {
    id: 'mock-3',
    platform: 'google',
    platform_id: 'mock-3',
    business_id: 'demo',
    business_name: 'Bien Vinh Hao 2 Seafood Restaurant',
    author: 'David Nguyen',
    rating: 3,
    content: 'Food was average, nothing particularly special. Pricing is a bit steep compared to nearby spots. Service was quick but staff seemed indifferent.',
    sentiment_score: -0.1,
    sentiment_label: 'neutral',
    topics: ['pricing', 'service attitude', 'food quality'],
    is_processed: true,
    published_at: '2026-03-13T18:30:00Z',
    created_at: '2026-03-13T18:30:00Z',
  },
  {
    id: 'mock-4',
    platform: 'google',
    platform_id: 'mock-4',
    business_id: 'demo',
    business_name: 'Bien Vinh Hao 2 Seafood Restaurant',
    author: 'Emily Carter',
    rating: 5,
    content: 'The cheese-grilled lobster was absolutely incredible! Salt-and-pepper crab was outstanding too. My whole family had a fantastic time.',
    sentiment_score: 0.95,
    sentiment_label: 'positive',
    topics: ['grilled lobster', 'salt pepper crab', 'family dining'],
    is_processed: true,
    published_at: '2026-03-12T12:15:00Z',
    created_at: '2026-03-12T12:15:00Z',
  },
  {
    id: 'mock-5',
    platform: 'google',
    platform_id: 'mock-5',
    business_id: 'demo',
    business_name: 'Bien Vinh Hao 2 Seafood Restaurant',
    author: 'Robert Lee',
    rating: 2,
    content: 'Disappointed this visit. The fish did not smell fresh. Tables were old and unclean. Will not be returning.',
    sentiment_score: -0.78,
    sentiment_label: 'negative',
    topics: ['fish freshness', 'hygiene', 'facilities'],
    is_processed: true,
    published_at: '2026-03-11T19:45:00Z',
    created_at: '2026-03-11T19:45:00Z',
  },
  {
    id: 'mock-6',
    platform: 'google',
    platform_id: 'mock-6',
    business_id: 'demo',
    business_name: 'Bien Vinh Hao 2 Seafood Restaurant',
    author: 'Jessica Wang',
    rating: 5,
    content: 'The seafood hotpot was phenomenal — packed with fresh shellfish and a rich, flavourful broth. Staff were cheerful and very helpful with menu recommendations.',
    sentiment_score: 0.88,
    sentiment_label: 'positive',
    topics: ['seafood hotpot', 'broth quality', 'menu recommendations'],
    is_processed: true,
    published_at: '2026-03-10T13:00:00Z',
    created_at: '2026-03-10T13:00:00Z',
  },
]

const MOCK_METRICS = {
  total: 127,
  positivePct: 71,
  negativePct: 14,
  avgRating: 4.2,
}

const MOCK_TOPICS = [
  { topic: 'fresh seafood', count: 38, sentiment: 'positive' as const },
  { topic: 'service quality', count: 31, sentiment: 'positive' as const },
  { topic: 'pricing', count: 27, sentiment: 'neutral' as const },
  { topic: 'ocean view', count: 24, sentiment: 'positive' as const },
  { topic: 'wait time', count: 18, sentiment: 'negative' as const },
  { topic: 'hygiene', count: 12, sentiment: 'negative' as const },
  { topic: 'ambiance', count: 22, sentiment: 'positive' as const },
  { topic: 'seafood hotpot', count: 15, sentiment: 'positive' as const },
]

const MOCK_INSIGHTS = [
  {
    id: 1,
    icon: '',
    title: 'Seafood freshness is your top strength',
    body: '38 reviews mention fresh seafood positively. Customers consistently praise the quality of shrimp, crab, and fish dishes — a key differentiator vs. nearby competitors.',
  },
  {
    id: 2,
    icon: '',
    title: 'Wait times spike on weekends',
    body: '18 reviews flag slow service on Saturday & Sunday evenings. Consider adding 2 extra servers during peak hours to protect your 4.2★ average rating.',
  },
  {
    id: 3,
    icon: '',
    title: 'Seafood hotpot drives repeat visits',
    body: 'Customers who mention hotpot give an average rating of 4.8★ — significantly above the 4.2★ overall average. Feature it more prominently on your menu and social channels.',
  },
]

export default function DashboardPage() {
  const [platform, setPlatform] = useState('')
  const [sentiment, setSentiment] = useState('')

  const { data, isLoading } = useReviews({
    platform: platform || undefined,
    limit: 20,
  })

  const hasRealData = (data?.total ?? 0) > 0
  const items = hasRealData ? (data?.items ?? []) : MOCK_REVIEWS
  const total = hasRealData ? (data?.total ?? 0) : MOCK_METRICS.total

  const positiveCount = items.filter((r) => r.sentiment_label === 'positive').length
  const negativeCount = items.filter((r) => r.sentiment_label === 'negative').length
  const positivePct = hasRealData
    ? (items.length > 0 ? Math.round((positiveCount / items.length) * 100) : 0)
    : MOCK_METRICS.positivePct
  const negativePct = hasRealData
    ? (items.length > 0 ? Math.round((negativeCount / items.length) * 100) : 0)
    : MOCK_METRICS.negativePct

  const ratings = items.map((r) => r.rating).filter((r): r is number => r !== null)
  const avgRating = hasRealData
    ? (ratings.length > 0 ? (ratings.reduce((a, b) => a + b, 0) / ratings.length).toFixed(1) : '—')
    : MOCK_METRICS.avgRating.toFixed(1)

  const filteredReviews = sentiment
    ? items.filter((r) => r.sentiment_label === sentiment)
    : items

  return (
    <div className="min-h-full">
      <TopNav title="Dashboard" subtitle="7-day overview · Bien Vinh Hao 2 Seafood Restaurant" />

      <div className="p-6 space-y-6">

        {/* Demo banner */}
        {!hasRealData && !isLoading && (
          <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 px-4 py-3 text-xs text-indigo-300 flex items-center gap-2">
            <Sparkles className="w-3.5 h-3.5 shrink-0" />
            Showing sample data — connect a data source to see your real reviews
          </div>
        )}

        {/* Metric cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          <MetricCard
            title="Total Reviews"
            value={total}
            change="+12%"
            changeType="positive"
            description="Across all platforms, de-duplicated"
            icon={<MessageSquare className="w-5 h-5 text-indigo-400" />}
            iconBg="bg-indigo-600/20"
          />
          <MetricCard
            title="Positive Sentiment"
            value={`${positivePct}%`}
            change="+3%"
            changeType="positive"
            description="LLM-classified via Llama 3.3 70B"
            icon={<TrendingUp className="w-5 h-5 text-green-400" />}
            iconBg="bg-green-600/20"
          />
          <MetricCard
            title="Negative Sentiment"
            value={`${negativePct}%`}
            change="-1%"
            changeType="positive"
            description="Lower is better"
            icon={<TrendingDown className="w-5 h-5 text-red-400" />}
            iconBg="bg-red-600/20"
          />
          <MetricCard
            title="Avg Rating"
            value={`${avgRating}★`}
            changeType="neutral"
            description="Across Google Maps reviews"
            icon={<Star className="w-5 h-5 text-yellow-400" />}
            iconBg="bg-yellow-600/20"
          />
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {/* Sentiment trend */}
          <div className="xl:col-span-2 rounded-xl bg-slate-900 border border-slate-800 p-5 shadow-soft">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-slate-200">Sentiment Trend</h2>
                <p className="text-xs text-slate-500 mt-0.5">Last 30 days · multilingual-e5-base embeddings</p>
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
              {[0, 40, 80, 120, 160].map((y) => (
                <line key={y} x1="0" y1={y} x2="600" y2={y} stroke="#1e293b" strokeWidth="1" />
              ))}
              <polyline fill="url(#posGrad)" stroke="none"
                points="0,120 60,100 120,90 180,70 240,80 300,60 360,50 420,65 480,45 540,55 600,40 600,160 0,160" />
              <polyline fill="none" stroke="#10b981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                points="0,120 60,100 120,90 180,70 240,80 300,60 360,50 420,65 480,45 540,55 600,40" />
              <polyline fill="url(#negGrad)" stroke="none"
                points="0,140 60,135 120,138 180,130 240,132 300,125 360,128 420,122 480,118 540,120 600,115 600,160 0,160" />
              <polyline fill="none" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                points="0,140 60,135 120,138 180,130 240,132 300,125 360,128 420,122 480,118 540,120 600,115" />
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
                <circle cx="60" cy="60" r="45" fill="none" stroke="#1e293b" strokeWidth="18" />
                <circle cx="60" cy="60" r="45" fill="none" stroke="#6366f1" strokeWidth="18"
                  strokeDasharray="127 155" strokeDashoffset="0" transform="rotate(-90 60 60)" />
                <circle cx="60" cy="60" r="45" fill="none" stroke="#06b6d4" strokeWidth="18"
                  strokeDasharray="99 183" strokeDashoffset="-127" transform="rotate(-90 60 60)" />
                <circle cx="60" cy="60" r="45" fill="none" stroke="#8b5cf6" strokeWidth="18"
                  strokeDasharray="56 226" strokeDashoffset="-226" transform="rotate(-90 60 60)" />
              </svg>
            </div>
            <div className="space-y-2 mt-3">
              {[
                { label: 'Google', pct: '45%', color: 'bg-indigo-500' },
                { label: 'Reddit', pct: '35%', color: 'bg-cyan-500' },
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

        {/* AI Insights + Top Topics */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {/* AI Insights */}
          <div className="xl:col-span-2 rounded-xl bg-slate-900 border border-slate-800 p-5 shadow-soft">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <h2 className="text-sm font-semibold text-slate-200">AI Insights</h2>
              <span className="ml-auto text-[10px] text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
                Llama 3.3 70B · updated 2h ago
              </span>
            </div>
            <div className="space-y-3">
              {MOCK_INSIGHTS.map((insight) => (
                <div key={insight.id} className="rounded-lg bg-slate-800/50 border border-slate-700/50 p-4">
                  <div className="flex items-start gap-3">
                    <span className="text-lg shrink-0">{insight.icon}</span>
                    <div>
                      <p className="text-sm font-medium text-slate-200">{insight.title}</p>
                      <p className="text-xs text-slate-400 mt-1 leading-relaxed">{insight.body}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Top Topics */}
          <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 shadow-soft">
            <div className="flex items-center gap-2 mb-4">
              <Tag className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-semibold text-slate-200">Top Topics</h2>
            </div>
            <div className="space-y-2">
              {MOCK_TOPICS.map(({ topic, count, sentiment }) => (
                <div key={topic} className="flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-xs text-slate-300 truncate">{topic}</span>
                      <span className="text-[10px] text-slate-500 ml-2 shrink-0">{count}</span>
                    </div>
                    <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          sentiment === 'positive' ? 'bg-green-500/70' :
                          sentiment === 'negative' ? 'bg-red-500/70' : 'bg-slate-500/70'
                        }`}
                        style={{ width: `${(count / 38) * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-slate-600 mt-4">Extracted by LLM · colour = sentiment</p>
          </div>
        </div>

        {/* Review volume bar chart */}
        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 shadow-soft">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-slate-200">Review Volume</h2>
              <p className="text-xs text-slate-500 mt-0.5">Daily ingestion · async Celery pipeline</p>
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
          <div className="flex justify-between mt-2">
            {['Mar 4', '', '', '', 'Mar 8', '', '', '', 'Mar 12', '', '', '', '', 'Mar 17'].map((label, i) => (
              <span key={i} className="flex-1 text-center text-[10px] text-slate-600">{label}</span>
            ))}
          </div>
        </div>

        {/* Reviews table with filters */}
        <div className="space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-200">Recent Reviews</h2>
              <p className="text-xs text-slate-500 mt-0.5">Ingested via SerpAPI · cleaned · LLM-processed</p>
            </div>
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
