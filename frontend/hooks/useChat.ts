'use client'

import { useState, useCallback } from 'react'
import { sendChatMessage } from '@/lib/api-client'
import type { ChatMessage } from '@/types'

const DEFAULT_BUSINESS_ID = 'ChIJN1t_tDeuEmsRUsoyG83frY4'

export interface ChatEntry {
  role: ChatMessage['role']
  content: string
  sources?: string[]
  isLoading?: boolean
}

export function useChat(businessId: string = DEFAULT_BUSINESS_ID) {
  const [entries, setEntries] = useState<ChatEntry[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const sendMessage = useCallback(
    async (question: string) => {
      if (!question.trim() || isLoading) return

      const userEntry: ChatEntry = { role: 'user', content: question }
      const placeholderEntry: ChatEntry = { role: 'assistant', content: '', isLoading: true }

      setEntries((prev) => [...prev, userEntry, placeholderEntry])
      setIsLoading(true)
      setError(null)

      // Build messages array from full history for multi-turn context
      const messages: ChatMessage[] = [
        ...entries.map((e) => ({ role: e.role, content: e.content })),
        { role: 'user', content: question },
      ]

      try {
        const res = await sendChatMessage({ business_id: businessId, messages })
        setEntries((prev) => [
          ...prev.slice(0, -1), // remove placeholder
          { role: 'assistant', content: res.answer, sources: res.sources },
        ])
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Something went wrong'
        setError(msg)
        setEntries((prev) => prev.slice(0, -1)) // remove placeholder
      } finally {
        setIsLoading(false)
      }
    },
    [entries, isLoading, businessId]
  )

  const clearChat = useCallback(() => {
    setEntries([])
    setError(null)
  }, [])

  return { entries, isLoading, error, sendMessage, clearChat }
}
