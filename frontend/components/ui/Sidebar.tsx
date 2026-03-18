'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  MessageSquare,
  Brain,
  GitCompare,
  Bot,
  Database,
  Settings,
  Sparkles,
  PanelLeft,
  RefreshCw,
} from 'lucide-react'
import clsx from 'clsx'

const navItems = [
  { label: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { label: 'Reviews', href: '/reviews', icon: MessageSquare },
  { label: 'AI Insights', href: '/insights', icon: Brain },
  { label: 'Competitor Analysis', href: '/competitors', icon: GitCompare },
  { label: 'AI Chat', href: '/ai-chat', icon: Bot },
  { label: 'Data Sources', href: '/settings/data-sources', icon: Database },
  { label: 'Settings', href: '/settings', icon: Settings },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="w-[280px] h-screen sticky top-0 bg-slate-900 border-r border-slate-800 flex flex-col shadow-panel overflow-y-auto">
      {/* Brand */}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-slate-800">
        <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center flex-shrink-0">
          <Brain className="w-4 h-4 text-white" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-100 truncate">CustomerVoice AI</p>
          <p className="text-xs text-slate-400 truncate">Intelligence Dashboard</p>
        </div>
        <button className="ml-auto text-slate-500 hover:text-slate-300 transition-colors flex-shrink-0">
          <PanelLeft className="w-4 h-4" />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {navItems.map(({ label, href, icon: Icon }) => {
          const isActive = pathname === href || (href !== '/dashboard' && pathname.startsWith(href))
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150',
                isActive
                  ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              )}
            >
              <Icon
                className={clsx('w-4 h-4 flex-shrink-0', isActive ? 'text-indigo-400' : 'text-slate-500')}
              />
              {label}
              {isActive && (
                <span className="ml-auto w-1.5 h-1.5 rounded-full bg-indigo-400" />
              )}
            </Link>
          )
        })}
      </nav>

      {/* Bottom insight card */}
      <div className="px-3 pb-4">
        <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4 shadow-soft">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="w-4 h-4 text-cyan-400 flex-shrink-0" />
            <p className="text-xs font-semibold text-slate-200">Insight refresh</p>
          </div>
          <p className="text-xs text-slate-400 mb-3 leading-relaxed">
            AI insights update every 2 hours
          </p>
          <button className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-indigo-400 text-xs font-medium transition-colors">
            <RefreshCw className="w-3 h-3" />
            Run now
          </button>
        </div>
      </div>
    </aside>
  )
}
