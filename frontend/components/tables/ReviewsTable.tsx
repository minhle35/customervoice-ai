'use client'

import clsx from 'clsx'
import { MessageSquare, Bot, MessageCircle, Star } from 'lucide-react'
import type { Review, Platform, SentimentLabel } from '@/types'

interface ReviewsTableProps {
  reviews: Review[]
  isLoading: boolean
}

function PlatformIcon({ platform }: { platform: Platform }) {
  if (platform === 'google') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-indigo-400">
        <MessageSquare className="w-3.5 h-3.5" />
        Google
      </span>
    )
  }
  if (platform === 'reddit') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-cyan-400">
        <Bot className="w-3.5 h-3.5" />
        Reddit
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-400">
      <MessageCircle className="w-3.5 h-3.5" />
      Facebook
    </span>
  )
}

function SentimentBadge({ label }: { label: SentimentLabel | null }) {
  if (!label) return <span className="text-xs text-slate-500">—</span>
  return (
    <span
      className={clsx(
        'inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize',
        label === 'positive' && 'bg-green-400/10 text-green-400',
        label === 'negative' && 'bg-red-400/10 text-red-400',
        label === 'neutral' && 'bg-slate-700 text-slate-400'
      )}
    >
      {label}
    </span>
  )
}

function StarRating({ rating }: { rating: number | null }) {
  if (rating === null) return <span className="text-xs text-slate-500">—</span>
  return (
    <div className="flex items-center gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star
          key={i}
          className={clsx(
            'w-3 h-3',
            i < rating ? 'text-yellow-400 fill-yellow-400' : 'text-slate-700'
          )}
        />
      ))}
    </div>
  )
}

function SkeletonRow() {
  return (
    <tr className="border-b border-slate-800">
      {Array.from({ length: 5 }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3 rounded bg-slate-800 animate-pulse" style={{ width: `${60 + i * 10}%` }} />
        </td>
      ))}
    </tr>
  )
}

function formatDate(dateStr: string | null) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export function ReviewsTable({ reviews, isLoading }: ReviewsTableProps) {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 shadow-soft overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-900/80">
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Platform</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Review</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Rating</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Sentiment</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Date</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)
            ) : reviews.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-slate-500">
                  <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p className="text-sm">No reviews yet</p>
                  <p className="text-xs mt-1">Connect a data source to start collecting reviews</p>
                </td>
              </tr>
            ) : (
              reviews.map((review) => (
                <tr
                  key={review.id}
                  className="border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors"
                >
                  <td className="px-4 py-3 whitespace-nowrap">
                    <PlatformIcon platform={review.platform} />
                  </td>
                  <td className="px-4 py-3 max-w-xs">
                    <p className="text-slate-300 text-xs leading-relaxed max-h-24 overflow-y-auto pr-1">{review.content}</p>
                    {review.topics && review.topics.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {review.topics.slice(0, 3).map((topic) => (
                          <span
                            key={topic}
                            className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800 text-slate-400 border border-slate-700/50"
                          >
                            {topic}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <StarRating rating={review.rating} />
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <SentimentBadge label={review.sentiment_label} />
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500">
                    {formatDate(review.published_at ?? review.created_at)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
