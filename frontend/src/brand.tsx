// Our own mark: two orbit arcs (blue and green) around an "E". A nod to Empower's colours, not their logo.
export function BrandMark({ size = 34, tone = 'light' }: { size?: number; tone?: 'light' | 'dark' }) {
  const ink = tone === 'light' ? '#0a2463' : '#ffffff'
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <defs>
        <linearGradient id={`bm-b-${tone}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3aa0ff" />
          <stop offset="1" stopColor="#1452d6" />
        </linearGradient>
        <linearGradient id={`bm-g-${tone}`} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#2fbf63" />
          <stop offset="1" stopColor="#00b3e6" />
        </linearGradient>
      </defs>
      <circle cx="20" cy="20" r="19" fill={tone === 'light' ? '#eef4ff' : '#ffffff'} opacity={tone === 'light' ? 1 : 0.08} />
      <path d="M6 24 A15 15 0 0 1 31 8.5" fill="none" stroke={`url(#bm-b-${tone})`} strokeWidth="3.4" strokeLinecap="round" />
      <path d="M34 16 A15 15 0 0 1 9 31.5" fill="none" stroke={`url(#bm-g-${tone})`} strokeWidth="3.4" strokeLinecap="round" />
      <text x="20" y="26.5" textAnchor="middle" fontFamily="Inter, Segoe UI, sans-serif" fontWeight="750" fontSize="17" fill={ink}>E</text>
    </svg>
  )
}
