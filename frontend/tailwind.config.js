/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Muted text: the Tailwind defaults for slate-500/600 measure 3.7:1 and
        // 2.4:1 on the card surface (below WCAG AA 4.5:1). These overrides keep
        // the same class names but meet AA on every surface colour used here.
        slate: { 500: '#8493a8', 600: '#8493a8' },
        surface: {
          DEFAULT: '#0b0e14',
          raised: '#11151f',
          card: '#141924',
          border: '#232a38',
        },
        accent: {
          DEFAULT: '#6366f1',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      keyframes: {
        'slide-in': { from: { transform: 'translateX(24px)', opacity: '0' }, to: { transform: 'translateX(0)', opacity: '1' } },
        'fade-in': { from: { opacity: '0', transform: 'translateY(4px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
      },
      animation: { 'fade-in': 'fade-in 160ms ease-out', 'slide-in': 'slide-in 220ms cubic-bezier(0.16, 1, 0.3, 1)' },
      boxShadow: {
        panel: '0 1px 2px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.03)',
      },
    },
  },
  plugins: [],
}
