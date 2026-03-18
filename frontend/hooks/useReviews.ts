'use client'

import { useQuery } from '@tanstack/react-query'
import { getReviews, type GetReviewsParams } from '@/lib/api-client'
import type { ReviewListResponse } from '@/types'

export function useReviews(params?: GetReviewsParams) {
  const { data, isLoading, error } = useQuery<ReviewListResponse, Error>({
    queryKey: ['reviews', params],
    queryFn: () => getReviews(params),
  })

  return { data, isLoading, error }
}
