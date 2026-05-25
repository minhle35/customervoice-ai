'use client'

import { useState } from 'react'
import {
  MapPin,
  AlertCircle,
  Loader2,
  Play,
  Search,
  Star,
  CheckCircle2,
} from 'lucide-react'
import { searchPlaces, triggerIngestion } from '@/lib/api-client'
import type { PlaceResult } from '@/lib/api-client'

const COUNTRIES = [
  { code: 'au', label: 'Australia' },
  { code: 'us', label: 'United States' },
  { code: 'vn', label: 'Vietnam' },
  { code: 'gb', label: 'United Kingdom' },
  { code: 'sg', label: 'Singapore' },
]

interface Props {
  onStarted: (taskId: string) => void
}

export function DataPipelineStarter({ onStarted }: Props) {
  const [query, setQuery] = useState('')
  const [country, setCountry] = useState('au')
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [results, setResults] = useState<PlaceResult[] | null>(null)
  const [selected, setSelected] = useState<PlaceResult | null>(null)
  const [maxReviews, setMaxReviews] = useState(100)
  const [ingesting, setIngesting] = useState(false)
  const [ingestError, setIngestError] = useState<string | null>(null)

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setSearchError(null)
    setResults(null)
    setSelected(null)
    setSearching(true)
    try {
      const places = await searchPlaces(query.trim(), country)
      setResults(places)
      if (places.length === 0) setSearchError('No businesses found. Try a different name or country.')
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : 'Search failed')
    } finally {
      setSearching(false)
    }
  }

  async function handleStartIngestion() {
    if (!selected) return
    setIngestError(null)
    setIngesting(true)
    try {
      const { task_id } = await triggerIngestion('google', {
        platform: 'google',
        params: {
          data_id: selected.data_id,
          ...(selected.place_id ? { place_id: selected.place_id } : {}),
          place_name: selected.title,
          max_reviews: maxReviews,
        },
      })
      onStarted(task_id)
    } catch (err) {
      setIngestError(err instanceof Error ? err.message : 'Failed to start ingestion')
    } finally {
      setIngesting(false)
    }
  }

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-6 shadow-soft space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-indigo-600/20 flex items-center justify-center flex-shrink-0">
          <MapPin className="w-5 h-5 text-indigo-400" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Google Maps Reviews</h2>
          <p className="text-xs text-slate-400">Search a business, select it, and run the ingestion pipeline</p>
        </div>
      </div>

      {/* Platform tabs */}
      <div className="flex gap-2">
        <span className="px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600/20 text-indigo-400 border border-indigo-500/30">
          Google Maps
        </span>
        <span className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-500 border border-slate-700/50 cursor-not-allowed">
          Reddit — coming soon
        </span>
        <span className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-500 border border-slate-700/50 cursor-not-allowed">
          Facebook — coming soon
        </span>
      </div>

      {/* Step 1 — Search */}
      <form onSubmit={handleSearch} className="space-y-3">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Step 1 — Find business</p>
        <div className="flex gap-2">
          <input
            type="text"
            required
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. Bien Vinh Hao 2 Seafood Restaurant"
            className="flex-1 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 transition-colors"
          />
          <select
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 transition-colors"
          >
            {COUNTRIES.map((c) => (
              <option key={c.code} value={c.code}>{c.label}</option>
            ))}
          </select>
          <button
            type="submit"
            disabled={searching}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed text-slate-200 text-sm font-medium transition-colors"
          >
            {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Search
          </button>
        </div>

        {searchError && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>{searchError}</span>
          </div>
        )}
      </form>

      {/* Step 2 — Pick a result */}
      {results && results.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Step 2 — Select business</p>
          <div className="space-y-2">
            {results.map((place) => {
              const isSelected = selected?.data_id === place.data_id
              return (
                <button
                  key={place.data_id}
                  type="button"
                  onClick={() => setSelected(place)}
                  className={`w-full text-left px-4 py-3 rounded-lg border transition-all ${
                    isSelected
                      ? 'bg-indigo-600/20 border-indigo-500/40 text-slate-100'
                      : 'bg-slate-800/60 border-slate-700/50 text-slate-300 hover:border-slate-600'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{place.title}</p>
                      {place.address && (
                        <p className="text-xs text-slate-400 mt-0.5 truncate">{place.address}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      {place.rating && (
                        <span className="flex items-center gap-1 text-xs text-yellow-400">
                          <Star className="w-3 h-3 fill-yellow-400" />
                          {place.rating}
                          {place.reviews_count && (
                            <span className="text-slate-500">({place.reviews_count})</span>
                          )}
                        </span>
                      )}
                      {isSelected && <CheckCircle2 className="w-4 h-4 text-indigo-400" />}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Step 3 — Start */}
      {selected && (
        <div className="space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Step 3 — Run ingestion</p>
          <div className="px-4 py-3 rounded-lg bg-slate-800/60 border border-slate-700/50 text-xs text-slate-400 space-y-1">
            <p><span className="text-slate-500">Business:</span> <span className="text-slate-200">{selected.title}</span></p>
            {selected.place_id && (
              <p><span className="text-slate-500">Place ID (business_id):</span> <span className="font-mono text-slate-300">{selected.place_id}</span></p>
            )}
            <p><span className="text-slate-500">Data ID:</span> <span className="font-mono text-slate-300">{selected.data_id}</span></p>
          </div>

          <div className="flex items-center gap-3">
            <label htmlFor="max-reviews" className="text-xs text-slate-400 whitespace-nowrap">
              Max reviews to fetch
            </label>
            <input
              id="max-reviews"
              type="number"
              min={1}
              max={500}
              value={maxReviews}
              onChange={(e) => setMaxReviews(Math.max(1, parseInt(e.target.value) || 1))}
              className="w-24 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 transition-colors"
            />
          </div>

          {ingestError && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
              <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{ingestError}</span>
            </div>
          )}

          <button
            type="button"
            onClick={handleStartIngestion}
            disabled={ingesting}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
          >
            {ingesting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Queuing job…
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                Start Ingestion
              </>
            )}
          </button>
        </div>
      )}
    </div>
  )
}
