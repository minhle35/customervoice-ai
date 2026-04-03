export type Platform = 'google' | 'reddit' | 'facebook'
export type SentimentLabel = 'positive' | 'negative' | 'neutral'

export interface Review {
  id: string
  platform: Platform
  platform_id: string
  business_id: string
  business_name: string | null
  author: string | null
  rating: number | null
  content: string
  sentiment_score: number | null
  sentiment_label: SentimentLabel | null
  topics: string[] | null
  is_processed: boolean
  published_at: string | null
  created_at: string
}

export interface ReviewListResponse {
  total: number
  items: Review[]
}

// ---------------------------------------------------------------------------
// Chat / RAG
// ---------------------------------------------------------------------------

export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  role: ChatRole
  content: string
}

export interface ChatRequest {
  business_id: string
  messages: ChatMessage[]
}

export interface ChatResponse {
  answer: string
  sources: string[] // review UUIDs
}
