import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Dev parity with prod ALB path-routing: send /api/* to FastAPI so the
  // browser only ever talks to its own origin (no CORS in either env).
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
