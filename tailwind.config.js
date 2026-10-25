/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js",
  ],
  theme: {
    extend: {
      // Jetons de la charte Zyphro (app/static/css/charte.css) : suivent le thème clair/foncé
      colors: {
        accent:        "rgb(var(--tw-accent) / <alpha-value>)",
        "accent-dark": "rgb(var(--tw-accent-dark) / <alpha-value>)",
        bg:            "rgb(var(--tw-bg) / <alpha-value>)",
        card:          "rgb(var(--tw-card) / <alpha-value>)",
        sidebar:       "rgb(var(--tw-sidebar) / <alpha-value>)",
        surface:       "rgb(var(--tw-surface) / <alpha-value>)",
        inp:           "rgb(var(--tw-inp) / <alpha-value>)",
        dim:           "rgb(var(--tw-dim) / <alpha-value>)",
        muted:         "rgb(var(--tw-muted) / <alpha-value>)",
        txt:           "rgb(var(--tw-txt) / <alpha-value>)",
        surface2:      "rgb(var(--tw-surface2) / <alpha-value>)",
        fg:            "rgb(var(--fg-rgb) / <alpha-value>)",   // voile : clair sur foncé, foncé sur clair
        emerald: {
          DEFAULT: "#10b981",
          900:     "#064e3b",
        },
      },
      fontFamily: {
        sans:    ['"Instrument Sans"', "system-ui", "sans-serif"],
        display: ['"Bricolage Grotesque"', '"Instrument Sans"', "system-ui", "sans-serif"],
        mono:    ['"Martian Mono"', "ui-monospace", "monospace"],
      },
      borderColor: {
        DEFAULT: "rgb(var(--fg-rgb) / 0.12)",
      },
    },
  },
  plugins: [
    require("@tailwindcss/forms"),
  ],
  /* Désactivé pendant la migration progressive : main.css coexiste avec Tailwind.
     À activer quand main.css est totalement supprimé (fin Phase 2). */
  corePlugins: {
    preflight: false,
  },
};
