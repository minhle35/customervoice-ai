'use client'

import { useState, useCallback, useEffect } from 'react'
import { sendChatMessage, getBusinesses } from '@/lib/api-client'
import type { Business } from '@/lib/api-client'
import type { ChatMessage } from '@/types'

export interface ChatEntry {
  role: ChatMessage['role']
  content: string
  sources?: string[]
  isLoading?: boolean
}

export function useChat() {
  const [entries, setEntries] = useState<ChatEntry[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [businesses, setBusinesses] = useState<Business[]>([])
  const [selectedBusinessId, setSelectedBusinessId] = useState<string | null>(null)

  useEffect(() => {
    getBusinesses().then((list) => {
      setBusinesses(list)
      if (list.length > 0) setSelectedBusinessId(list[0].business_id)
    }).catch(() => {/* no businesses yet */})
  }, [])

  const sendMessage = useCallback(
    async (question: string) => {
      if (!question.trim() || isLoading || !selectedBusinessId) return

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
        const res = await sendChatMessage({ business_id: selectedBusinessId, messages })
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
    [entries, isLoading, selectedBusinessId]
  )

  const clearChat = useCallback(() => {
    setEntries([])
    setError(null)
  }, [])

  return { entries, isLoading, error, sendMessage, clearChat, businesses, selectedBusinessId, setSelectedBusinessId }
}
