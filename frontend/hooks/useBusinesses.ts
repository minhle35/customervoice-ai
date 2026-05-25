'use client'

import { useQuery } from '@tanstack/react-query'
import { getBusinesses, type Business } from '@/lib/api-client'

export function useBusinesses() {
  const { data, isLoading } = useQuery<Business[], Error>({
    queryKey: ['businesses'],
    queryFn: getBusinesses,
    staleTime: 60_000,
  })
  return { businesses: data ?? [], isLoading }
}
