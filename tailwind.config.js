/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: '#0d5d5a',
        'primary-container': '#0f7a72',
        'on-primary': '#ffffff',
        secondary: '#1f9d8a',
        'secondary-container': '#dff7f3',
        'on-secondary': '#ffffff',
        error: '#d94d3a',
        'error-container': '#ffe3dc',
        surface: '#f3f8f6',
        'surface-container': '#edf4f1',
        'surface-container-low': '#f9fbfa',
        'on-surface': '#113b39',
        'on-surface-variant': '#496766',
        outline: '#9bb8b4',
        'outline-variant': '#d5e8e4',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        display: ['Space Grotesk', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
