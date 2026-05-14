import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Dev-only proxy. In prod the ALB routes /api/* to FastAPI before Next sees
  // the request, so this rewrite would be dormant; gating it prevents it from
  // firing accidentally if the ALB rule ever drifts.
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
