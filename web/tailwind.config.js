/**
 * The design's density is specific enough (11.5px text, 22-25px controls, 1px rules) that
 * Tailwind's default scale is actively unhelpful here. `theme` is replaced WHOLESALE rather
 * than extended, so no default value can leak in and quietly break the rhythm.
 *
 * Colours point at the CSS variables declared in index.css, which is what makes the
 * data-theme dark toggle free — no `dark:` variants anywhere.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  // Character colours are picked by index at runtime (bg-s3, text-s3, border-s3).
  safelist: [{ pattern: /^(bg|text|border)-s[0-7]$/ }],
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      white: "#ffffff",
      black: "#000000",

      bg: "var(--bg)",
      panel: "var(--panel)",
      panel2: "var(--panel2)",
      panel3: "var(--panel3)",
      border: "var(--border)",
      border2: "var(--border2)",
      text: "var(--text)",
      dim: "var(--dim)",
      faint: "var(--faint)",
      accent: "var(--accent)",
      accent2: "var(--accent2)",
      soft: "var(--soft)",
      sel: "var(--sel)",
      top: "var(--top)",
      topfg: "var(--topfg)",
      good: "var(--good)",
      goodbg: "var(--goodbg)",
      warn: "var(--warn)",
      warnbg: "var(--warnbg)",
      bad: "var(--bad)",
      badbg: "var(--badbg)",

      cross: "var(--cross)",
      crossbg: "var(--crossbg)",
      crosspanel: "var(--crosspanel)",

      topfill: "var(--topfill)",
      topfill2: "var(--topfill2)",
      topline: "var(--topline)",
      topline2: "var(--topline2)",
      topsel: "var(--topsel)",
      topdim: "var(--topdim)",

      // Per-character colours, index = characters.color (see index.css).
      s0: "var(--s0)", s1: "var(--s1)", s2: "var(--s2)", s3: "var(--s3)",
      s4: "var(--s4)", s5: "var(--s5)", s6: "var(--s6)", s7: "var(--s7)",
    },

    /* Literal px, because the design specifies literal px. Every value is scaled by
       --font-scale (default 1, see src/index.css), so one variable can resize every
       text-* utility in the app without touching each call site. */
    fontSize: {
      "8.5": "calc(8.5px * var(--font-scale, 1))",
      "9.5": "calc(9.5px * var(--font-scale, 1))",
      10: "calc(10px * var(--font-scale, 1))",
      "10.5": "calc(10.5px * var(--font-scale, 1))",
      11: "calc(11px * var(--font-scale, 1))",
      "11.5": "calc(11.5px * var(--font-scale, 1))",
      12: "calc(12px * var(--font-scale, 1))",
      "12.5": "calc(12.5px * var(--font-scale, 1))",
      13: "calc(13px * var(--font-scale, 1))",
      "13.5": "calc(13.5px * var(--font-scale, 1))",
      14: "calc(14px * var(--font-scale, 1))",
      15: "calc(15px * var(--font-scale, 1))",
      17: "calc(17px * var(--font-scale, 1))",
      19: "calc(19px * var(--font-scale, 1))",
      21: "calc(21px * var(--font-scale, 1))",
      26: "calc(26px * var(--font-scale, 1))",
      30: "calc(30px * var(--font-scale, 1))",
    },

    /* px-14 means 14px. Keeps the design's odd values (5, 7, 9, 11) readable in markup
       instead of translating them through an abstract 4px-step scale. */
    spacing: {
      0: "0px",
      px: "1px",
      1: "1px",
      2: "2px",
      3: "3px",
      4: "4px",
      5: "5px",
      6: "6px",
      7: "7px",
      8: "8px",
      9: "9px",
      10: "10px",
      11: "11px",
      12: "12px",
      13: "13px",
      14: "14px",
      15: "15px",
      16: "16px",
      18: "18px",
      19: "19px",
      20: "20px",
      21: "21px",
      22: "22px",
      23: "23px",
      24: "24px",
      25: "25px",
      26: "26px",
      28: "28px",
      30: "30px",
      32: "32px",
      36: "36px",
      38: "38px",
      40: "40px",
      44: "44px",
      48: "48px",
      56: "56px",
      60: "60px",
      72: "72px",
      46: "46px",
      52: "52px",
      64: "64px",
      78: "78px",
      88: "88px",
      96: "96px",
      110: "110px",
      120: "120px",
      140: "140px",
      180: "180px",
      200: "200px",
      210: "210px",
      260: "260px",
      130: "130px",
      150: "150px",
      160: "160px",
      186: "186px",
      190: "190px",
      196: "196px",
      230: "230px",
      236: "236px",
      250: "250px",
      280: "280px",
      300: "300px",
      320: "320px",
      340: "340px",
      375: "375px",
      420: "420px",
      560: "560px",
      640: "640px",
      700: "700px",
      720: "720px",
      760: "760px",
      820: "820px",
      1000: "1000px",
      1100: "1100px",
      1120: "1120px",
    },

    fontFamily: {
      // sans tracks the user's typeface preference (see --font-family-sans in
      // index.css); mono is deliberately NOT preference-driven — "IBM Plex Mono for
      // every quantity" is a data-readability decision, not a personal taste one.
      sans: ["var(--font-family-sans)", "system-ui", "sans-serif"],
      mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      // Amharic text: Plex has no Ethiopic glyphs.
      eth: ["'Noto Sans Ethiopic'", "var(--font-family-sans)", "sans-serif"],
    },

    fontWeight: {
      normal: "400",
      medium: "500",
      semibold: "600",
      bold: "700",
    },

    borderRadius: {
      none: "0",
      1: "1px",
      2: "2px",
      3: "3px",
      4: "4px",
      6: "6px",
      full: "9999px",
    },

    borderWidth: {
      0: "0",
      DEFAULT: "1px",
      1: "1px",
      2: "2px",
      3: "3px",
    },

    letterSpacing: {
      tight: "-0.02em",
      normal: "0",
      wide: "0.01em",
      wider: "0.06em",
      widest: "0.07em",
      caps: "0.08em",
      label: "0.09em",
    },

    lineHeight: {
      none: "1",
      tight: "1.15",
      snug: "1.25",
      normal: "1.35",
      relaxed: "1.45",
      loose: "1.55",
      body: "1.6",
    },

    extend: {
      /* Panels are flush and divided by rules — there are no floating cards, so the
         shadow scale is deliberately empty apart from `none`. */
      boxShadow: {
        none: "none",
      },
    },
  },
  plugins: [],
};
