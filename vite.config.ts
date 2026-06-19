import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Set base to your repo name for GitHub Pages, e.g. '/fennec/'
  // Change this to match your GitHub repo name
  base: "/fennec/",
});
