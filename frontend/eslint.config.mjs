import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // These screens intentionally set state after async API refreshes or URL initialization.
    // The rule currently reports those indirect updates as synchronous effect mutations.
    files: ["src/app/dashboard/**/*.tsx", "src/app/sim/page.tsx", "src/app/overlay/page.tsx"],
    rules: { "react-hooks/set-state-in-effect": "off" },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
