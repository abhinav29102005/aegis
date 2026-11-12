import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        aegis: {
          bg: "#111513",
          surface: "#1B211D",
          secondary: "#222A24",
          panel: "#1B211D",
          card: "#161C18",
          border: "#28332B",
          "border-subtle": "#1E2620",
          "border-active": "#3B483E",
          "border-accent": "rgba(215, 241, 123, 0.35)",
          accent: "#D7F17B",
          "accent-hover": "#E2F694",
          "accent-muted": "rgba(215, 241, 123, 0.12)",
          copper: "#D58A62",
          "copper-muted": "rgba(213, 138, 98, 0.15)",
          text: {
            primary: "#F2F1E9",
            muted: "#A8B1A9",
            faint: "#657167",
          },
          emerald: "#D7F17B",
          amber: "#D58A62",
          rose: "#EF5350",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "Roboto",
          '"Helvetica Neue"',
          "Arial",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          '"Liberation Mono"',
          '"Courier New"',
          "monospace",
        ],
      },
      boxShadow: {
        editorial: "0 1px 0 0 rgba(215, 241, 123, 0.08), 0 2px 8px 0 rgba(0, 0, 0, 0.45)",
        panel: "0 4px 20px -2px rgba(0, 0, 0, 0.55)",
      },
    },
  },
  plugins: [],
};

export default config;
