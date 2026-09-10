/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: '#0E1A2B', 2: '#16263D', 3: '#22355A' },
        paper: { DEFAULT: '#F6F7F9', 2: '#FFFFFF' },
        line: { DEFAULT: '#E1E5EB', 2: '#CBD2DC' },
        oxford: { DEFAULT: '#1E3A5F', 2: '#2C4F7C', soft: '#E8EEF6' },
        seal: { DEFAULT: '#A8321F', soft: '#F8E9E5' },
        gilt: { DEFAULT: '#B8923E', soft: '#F6EFDD' },
        moss: { DEFAULT: '#2F6B4F', soft: '#E4F1E9' },
        slate: { 900: '#111827', 700: '#374151', 500: '#6B7280', 400: '#9CA3AF' },
      },
      fontFamily: {
        display: ['Fraunces', 'Georgia', 'serif'],
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(14,26,43,0.05), 0 1px 0 rgba(14,26,43,0.03)',
        lift: '0 8px 24px rgba(14,26,43,0.10)',
      },
    },
  },
  plugins: [],
}
