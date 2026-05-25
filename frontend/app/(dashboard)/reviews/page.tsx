'use client'

import { useState } from 'react'
import { TopNav } from '@/components/ui/TopNav'
import { ReviewsTable } from '@/components/tables/ReviewsTable'
import { useReviews } from '@/hooks/useReviews'
import { useBusinesses } from '@/hooks/useBusinesses'
import { Building2 } from 'lucide-react'

const PAGE_SIZE = 50

export default function ReviewsPage() {
  const [offset, setOffset] = useState(0)
  const [allReviews, setAllReviews] = useState<import('@/types').Review[]>([])
  const [selectedBusiness, setSelectedBusiness] = useState<string>('')

  const { businesses } = useBusinesses()

  const { data, isLoading } = useReviews({
    limit: PAGE_SIZE,
    offset,
    ...(selectedBusiness ? { business_id: selectedBusiness } : {}),
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const displayed = offset === 0 ? items : [...allReviews, ...items]
  const hasMore = displayed.length < total

  function handleBusinessChange(id: string) {
    setSelectedBusiness(id)
    setAllReviews([])
    setOffset(0)
  }

  function loadMore() {
    setAllReviews(displayed)
    setOffset((prev) => prev + PAGE_SIZE)
  }

  const selectedName = businesses.find((b) => b.business_id === selectedBusiness)?.business_name

  return (
    <div className="min-h-full">
      <TopNav
        title="Reviews"
        subtitle={total > 0 ? `${total.toLocaleString()} total reviews` : 'All customer reviews'}
      />

      <div className="p-6 space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-200">
              {selectedName ?? 'All Businesses'}
            </h2>
            {total > 0 && (
              <p className="text-xs text-slate-500 mt-0.5">
                Showing {displayed.length} of {total.toLocaleString()}
              </p>
            )}
          </div>

          {businesses.length > 0 && (
            <div className="flex items-center gap-2">
              <Building2 className="w-4 h-4 text-slate-500 flex-shrink-0" />
              <select
                value={selectedBusiness}
                onChange={(e) => handleBusinessChange(e.target.value)}
                className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 transition-colors"
              >
                <option value="">All businesses</option>
                {businesses.map((b) => (
                  <option key={b.business_id} value={b.business_id}>
                    {b.business_name ?? b.business_id}
                  </option>
                ))}
              </select>
            </div>
          )}
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
