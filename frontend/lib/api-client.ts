import type { ChatRequest, ChatResponse, Review, ReviewListResponse } from '@/types'

const BASE_URL = '/api'

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API error ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export interface GetReviewsParams {
  business_id?: string
  platform?: string
  is_processed?: boolean
  limit?: number
  offset?: number
}

export function getReviews(params?: GetReviewsParams): Promise<ReviewListResponse> {
  const qs = new URLSearchParams()
  if (params) {
    if (params.business_id !== undefined) qs.set('business_id', params.business_id)
    if (params.platform !== undefined) qs.set('platform', params.platform)
    if (params.is_processed !== undefined) qs.set('is_processed', String(params.is_processed))
    if (params.limit !== undefined) qs.set('limit', String(params.limit))
    if (params.offset !== undefined) qs.set('offset', String(params.offset))
  }
  const query = qs.toString()
  return apiFetch<ReviewListResponse>(`/reviews${query ? `?${query}` : ''}`)
}

export function getReview(id: string): Promise<Review> {
  return apiFetch<Review>(`/reviews/${id}`)
}

export interface PlaceResult {
  title: string
  data_id: string
  place_id: string | null
  address: string | null
  rating: number | null
  reviews_count: number | null
}

export function searchPlaces(query: string, country: string): Promise<PlaceResult[]> {
  const qs = new URLSearchParams({ q: query, country })
  return apiFetch<PlaceResult[]>(`/integrations/google/search?${qs}`)
}

export function triggerIngestion(
  platform: string,
  payload: { platform: string; business_id?: string; params: Record<string, string> }
): Promise<{ status: string; task_id: string }> {
  return apiFetch<{ status: string; task_id: string }>(`/integrations/${platform}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export interface TaskProgress {
  stage: 'fetching' | 'processing' | 'rate_limited'
  total: number
  processed: number
  skipped: number
  rate_limited: number
}

export interface TaskStatus {
  task_id: string
  status: 'PENDING' | 'STARTED' | 'PROGRESS' | 'SUCCESS' | 'FAILURE' | 'RETRY' | 'REVOKED'
  progress?: TaskProgress
  result?: { processed: number; skipped: number; rate_limited: number; total: number }
  error?: string
}

export function getTaskStatus(taskId: string): Promise<TaskStatus> {
  return apiFetch<TaskStatus>(`/integrations/tasks/${taskId}`)
}

export function triggerReprocess(limit = 100): Promise<{ status: string; task_id: string }> {
  return apiFetch<{ status: string; task_id: string }>(
    `/integrations/reprocess?limit=${limit}`,
    { method: 'POST' }
  )
}