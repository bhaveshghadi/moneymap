// The browser only ever talks to Next.js; /api/* is proxied to FastAPI, so
// the session cookie is same-origin and no CORS setup is needed.
const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  poweredByHeader: false,
  experimental: {
    // Backups are uploaded through the /api proxy: allow up to 2 GB (default 10 MB) and give a
    // large restore time to finish (default 30 s).
    proxyClientMaxBodySize: 2 * 1024 * 1024 * 1024,
    proxyTimeout: 10 * 60 * 1000,
  },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
