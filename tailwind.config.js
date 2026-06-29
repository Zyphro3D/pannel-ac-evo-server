/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js",
    "./node_modules/flowbite/**/*.js"
  ],
  theme: {
    extend: {
      colors: {
        accent:        "#e03535",
        "accent-dark": "#c62828",
        bg:            "#06080c",
        card:          "#0e1525",
        sidebar:       "#040508",
        surface:       "#111420",
        inp:           "#0a0f1c",
        dim:           "#8896a8",
        muted:         "#3d4a5c",
        txt:           "#e2e8f0",
        emerald: {
          DEFAULT: "#10b981",
          900:     "#064e3b",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      borderColor: {
        DEFAULT: "rgba(61,74,92,0.4)",
      },
    },
  },
  plugins: [
    require("@tailwindcss/forms"),
    require("flowbite/plugin"),
  ],
  /* Désactivé pendant la migration progressive : main.css coexiste avec Tailwind.
     À activer quand main.css est totalement supprimé (fin Phase 2). */
  corePlugins: {
    preflight: false,
  },
};
