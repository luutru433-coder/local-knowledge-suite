// SPDX-License-Identifier: MIT
// Copyright (c) 2026 John-IDK

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  }
});
