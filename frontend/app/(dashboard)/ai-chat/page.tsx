'use client'

import { useState, useRef, useEffect } from 'react'
import { Bot, Send, Trash2, Sparkles, User } from 'lucide-react'
import { TopNav } from '@/components/ui/TopNav'
import { useChat } from '@/hooks/useChat'

const SUGGESTED_QUESTIONS = [
  'What do customers complain about most?',
  'What are the top strengths of this business?',
  'How is the service quality perceived?',
  'What food items get the best reviews?',
]

function CitationText({ text }: { text: string }) {
  // Highlight [1], [2], [3] citation markers
  const parts = text.split(/(\[\d+\])/g)
  return (
    <span>
      {parts.map((part, i) =>
        /^\[\d+\]$/.test(part) ? (
          <span
            key={i}
            className="inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold bg-indigo-600/30 text-indigo-300 border border-indigo-500/40 mx-0.5 align-middle"
          >
            {part.slice(1, -1)}
          </span>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </span>
  )
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-bounce"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </div>
  )
}

export default function AIChatPage() {
  const { entries, isLoading, error, sendMessage, clearChat } = useChat()
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  function handleSend() {
    const q = input.trim()
    if (!q) return
    setInput('')
    sendMessage(q)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const isEmpty = entries.length === 0

  return (
    <div className="min-h-full flex flex-col">
      <TopNav title="AI Chat" subtitle="Ask questions about your customer reviews" />

      <div className="flex-1 flex flex-col p-6 gap-4 min-h-0">

        {/* Empty state */}
        {isEmpty && (
          <div className="flex-1 flex flex-col items-center justify-center gap-6 text-center">
            <div className="w-14 h-14 rounded-2xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center">
              <Bot className="w-7 h-7 text-indigo-400" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-200">Ask about your reviews</h2>
              <p className="text-xs text-slate-500 mt-1 max-w-xs">
                Powered by RAG — retrieves the most relevant reviews then generates a grounded answer with citations.
              </p>
            </div>

            {/* Suggested questions */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
              {SUGGESTED_QUESTIONS.map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  className="text-left px-4 py-3 rounded-xl bg-slate-900 border border-slate-800 hover:border-indigo-500/40 hover:bg-indigo-600/5 transition-all text-xs text-slate-400 hover:text-slate-200"
                >
                  <Sparkles className="w-3 h-3 text-indigo-400 inline mr-1.5 mb-0.5" />
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Message thread */}
        {!isEmpty && (
          <div className="flex-1 overflow-y-auto space-y-4 pr-1">
            <div className="flex justify-end">
              <button
                onClick={clearChat}
                className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors px-2.5 py-1.5 rounded-lg hover:bg-slate-800"
              >
                <Trash2 className="w-3 h-3" />
                Clear chat
              </button>
            </div>
            {entries.map((entry, i) => (
              <div
                key={i}
                className={`flex gap-3 ${entry.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
              >
                {/* Avatar */}
                <div
                  className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 ${
                    entry.role === 'user'
                      ? 'bg-indigo-600/30 border border-indigo-500/30'
                      : 'bg-slate-800 border border-slate-700'
                  }`}
                >
                  {entry.role === 'user' ? (
                    <User className="w-3.5 h-3.5 text-indigo-400" />
                  ) : (
                    <Bot className="w-3.5 h-3.5 text-slate-400" />
                  )}
                </div>

                {/* Bubble */}
                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    entry.role === 'user'
                      ? 'bg-indigo-600/20 border border-indigo-500/30 text-slate-200 rounded-tr-sm'
                      : 'bg-slate-900 border border-slate-800 text-slate-300 rounded-tl-sm'
                  }`}
                >
                  {entry.isLoading ? (
                    <TypingDots />
                  ) : (
                    <>
                      <CitationText text={entry.content} />
                      {entry.sources && entry.sources.length > 0 && (
                        <p className="text-[10px] text-slate-600 mt-2 border-t border-slate-800 pt-2">
                          Based on {entry.sources.length} review{entry.sources.length > 1 ? 's' : ''}
                        </p>
                      )}
                    </>
                  )}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}

        {/* Error banner */}
        {error && (
          <div className="rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-xs text-red-400">
            {error}
          </div>
        )}

        {/* Input bar */}
        <div className="rounded-2xl bg-slate-900 border border-slate-800 focus-within:border-indigo-500/50 transition-colors p-3 flex items-end gap-3">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question about your reviews…"
            rows={1}
            className="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-600 resize-none focus:outline-none max-h-32"
            style={{ lineHeight: '1.5rem' }}
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="w-8 h-8 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center flex-shrink-0"
          >
            <Send className="w-3.5 h-3.5 text-white" />
          </button>
        </div>

        <p className="text-center text-[10px] text-slate-700">
          Answers grounded in real reviews · RAG pipeline · Llama 3.3 70B via OpenRouter
        </p>
      </div>
    </div>
  )
}
