import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        slateDeep: {
          950: '#0b1220',
          930: '#0f172a',
        },
        indigoCV: '#6366f1',
        cyanCV: '#06b6d4',
        greenCV: '#10b981',
        redCV: '#ef4444',
      },
      boxShadow: {
        panel: '0 10px 30px rgba(0,0,0,0.35)',
        soft: '0 1px 0 rgba(255,255,255,0.05) inset, 0 12px 22px rgba(0,0,0,0.28)',
      },
    },
  },
  plugins: [],
}

export default config
