/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["Fraunces", "Georgia", "serif"],
        sans: ["Outfit", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        paper: "#f6f1ea",
        ink: "#1c1917",
        clay: "#9a3412",
        line: "#e4dbd1",
      },
    },
  },
  plugins: [],
};
