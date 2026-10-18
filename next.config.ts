import type { NextConfig } from 'next'
const config: NextConfig = {
  allowedDevOrigins: ['127.0.0.1', '[::1]'],
  distDir: process.env.CAREER_KITCHEN_FRONTEND_BUILD_DIR || '.next',
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Strict-Transport-Security', value: 'max-age=63072000' },
        ],
      },
    ]
  },
}
export default config
