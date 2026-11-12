// The browser only ever talks to Next.js; /api/* is proxied to FastAPI, so
// the session cookie is same-origin and no CORS setup is needed.
const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  poweredByHeader: false,
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
