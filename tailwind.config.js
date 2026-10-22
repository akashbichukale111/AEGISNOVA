/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        background: '#070A10',
        card: {
          DEFAULT: '#0D131F',
          border: '#1B2538',
          hover: '#131B2C',
        },
        navy: {
          950: '#070A10',
          900: '#0B0F19',
          850: '#0F1626',
          800: '#152037',
          700: '#1E2D4C',
          600: '#2A3F69',
        },
        aegis: {
          cyan: '#06B6D4',
          cyanLight: '#67E8F9',
          blue: '#0284C7',
          blueLight: '#38BDF8',
          emerald: '#10B981',
          amber: '#F59E0B',
          rose: '#EF4444',
          violet: '#8B5CF6',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
};
