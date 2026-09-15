/** @type {import("tailwindcss").Config} */
// One token system, two registers: the customer app sits on paper, the reviewer
// console on ink. The only saturated colours in either are the three outcomes —
// nothing is coloured for decoration, so the decision is the loudest thing on
// any screen it appears on.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#0E1A22", raised: "#17262F", hair: "#26363F", mute: "#8397A0" },
        paper: { DEFAULT: "#F3F5F4", raised: "#FFFFFF", hair: "#DFE5E3" },
        graphite: "#5A6B73",
        approve: "#1B7F5A",
        review: "#A8761F",
        decline: "#A63D52",
      },
      fontFamily: {
        sans: ["Archivo", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
      borderRadius: { card: "0.625rem" },
    },
  },
  plugins: [],
};
