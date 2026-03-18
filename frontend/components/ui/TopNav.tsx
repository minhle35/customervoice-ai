'use client'

import { Bell, Search } from 'lucide-react'

interface TopNavProps {
  title: string
  subtitle?: string
}

export function TopNav({ title, subtitle }: TopNavProps) {
  return (
    <header className="sticky top-0 z-10 flex items-center gap-4 px-6 py-3 bg-slate-900/80 backdrop-blur border-b border-slate-800">
      {/* Left: title */}
      <div className="min-w-0 mr-auto">
        <h1 className="text-base font-semibold text-slate-100 leading-tight">{title}</h1>
        {subtitle && (
          <p className="text-xs text-slate-400 leading-tight">{subtitle}</p>
        )}
      </div>

      {/* Center: search */}
      <div className="relative hidden md:block">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
        <input
          type="search"
          placeholder="Search reviews…"
          className="pl-8 pr-4 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 w-56 transition-all"
        />
      </div>

      {/* Right: actions */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <button className="relative p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">
          <Bell className="w-4 h-4" />
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-indigo-400" />
        </button>
        <button className="flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-lg hover:bg-slate-800 transition-colors">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-indigo-500 to-cyan-500 flex items-center justify-center text-white text-xs font-semibold flex-shrink-0">
            A
          </div>
          <span className="text-sm text-slate-300 font-medium">Avery</span>
        </button>
      </div>
    </header>
  )
}
