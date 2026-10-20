/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // ── Luxury Gold Palette ──
        primary: {
          DEFAULT: '#D4A32C',
          light:   '#EAC665',
          dark:    '#A97918',
        },
        accent: {
          DEFAULT: '#F0D68B',
          muted:   '#D4C4B0',
        },
        // ── Dark Backgrounds ──
        bg: {
          DEFAULT: 'var(--color-bg)',
          card:    'var(--color-bg-card)',
          elevated:'var(--color-bg-elevated)',
        },
        // ── Text ──
        content: {
          DEFAULT: 'var(--color-text)',
          muted:   'var(--color-text-muted)',
          subtle:  'var(--color-text-subtle)',
        },
        // ── Status ──
        success: '#22C55E',
        warning: '#F59E0B',
        danger:  '#EF4444',
        info:    '#3B82F6',
      },
      fontFamily: {
        ar:       ['Cairo', 'Tajawal', 'sans-serif'],
        en:       ['Inter', 'sans-serif'],
        'title-ar': ['Amiri', 'serif'],
        'title-en': ['Playfair Display', 'serif'],
      },
      borderRadius: {
        sm:  '6px',
        md:  '12px',
        lg:  '20px',
        xl:  '32px',
      },
      boxShadow: {
        gold:   '0 0 30px rgba(212, 163, 44, 0.15)',
        card:   '0 4px 24px rgba(0,0,0,0.35)',
        glow:   '0 0 60px rgba(212, 163, 44, 0.08)',
        inset:  'inset 0 1px 0 rgba(255,255,255,0.05)',
      },
      backgroundImage: {
        'gradient-gold':    'linear-gradient(135deg, #D4A32C, #F0D68B)',
        'gradient-surface': 'linear-gradient(180deg, #102C49, #061B32)',
        'gradient-card':    'linear-gradient(145deg, rgba(16,44,73,0.8), rgba(6,27,50,0.9))',
      },
      backdropBlur: {
        glass: '12px',
      },
    },
  },
  plugins: [],
}
