'use client'

import { useState } from 'react'
import { TopNav } from '@/components/ui/TopNav'
import { ReviewsTable } from '@/components/tables/ReviewsTable'
import { useReviews } from '@/hooks/useReviews'

const PAGE_SIZE = 50

export default function ReviewsPage() {
  const [offset, setOffset] = useState(0)
  const [allReviews, setAllReviews] = useState<import('@/types').Review[]>([])

  const { data, isLoading } = useReviews({ limit: PAGE_SIZE, offset })

  // Merge new page into accumulated list
  const items = data?.items ?? []
  const total = data?.total ?? 0

  // Combine already-loaded reviews with current page
  const displayed = offset === 0 ? items : [...allReviews, ...items]
  const hasMore = displayed.length < total

  function loadMore() {
    setAllReviews(displayed)
    setOffset((prev) => prev + PAGE_SIZE)
  }

  return (
    <div className="min-h-full">
      <TopNav
        title="Reviews"
        subtitle={total > 0 ? `${total.toLocaleString()} total reviews` : 'All customer reviews'}
      />

      <div className="p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-200">All Reviews</h2>
            {total > 0 && (
              <p className="text-xs text-slate-500 mt-0.5">
                Showing {displayed.length} of {total.toLocaleString()}
              </p>
            )}
          </div>
        </div>

        <ReviewsTable reviews={offset === 0 ? items : displayed} isLoading={isLoading && offset === 0} />

        {hasMore && (
          <div className="flex justify-center pt-2">
            <button
              onClick={loadMore}
              disabled={isLoading}
              className="px-5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-sm text-slate-300 font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoading ? 'Loading…' : `Load more (${total - displayed.length} remaining)`}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
