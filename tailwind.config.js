/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: '#003f87',
        'primary-container': '#0056b3',
        'on-primary': '#ffffff',
        secondary: '#006e25',
        'secondary-container': '#80f98b',
        'on-secondary': '#ffffff',
        error: '#ba1a1a',
        'error-container': '#ffdad6',
        surface: '#f8f9fa',
        'surface-container': '#edeeef',
        'surface-container-low': '#f3f4f5',
        'on-surface': '#191c1d',
        'on-surface-variant': '#424752',
        outline: '#727784',
        'outline-variant': '#c2c6d4',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        display: ['Space Grotesk', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
