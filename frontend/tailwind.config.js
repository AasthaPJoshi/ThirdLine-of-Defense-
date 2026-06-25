/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          bg:       '#040D1A',
          card:     '#0A1628',
          elevated: '#0F1F38',
          border:   '#1A2E4A',
          hover:    '#132040',
        },
        brand: {
          primary: '#1B6EF3',
          accent:  '#00D4FF',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
