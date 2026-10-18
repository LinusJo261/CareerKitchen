export class GatewayError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

export function assertSameOrigin(request: Request) {
  const origin = request.headers.get('origin')
  const url = new URL(request.url)
  const expected =
    process.env.CAREER_KITCHEN_SITE_URL ||
    `${url.protocol}//${request.headers.get('host') || url.host}`
  if (
    !origin ||
    origin !== expected ||
    request.headers.get('sec-fetch-site') === 'cross-site'
  ) {
    throw new GatewayError(
      403,
      'ORIGIN_FORBIDDEN',
      'Reload this page before trying again.',
    )
  }
}

export function isLoopbackHost(hostname: string) {
  return ['localhost', '127.0.0.1', '[::1]', '::1'].includes(hostname)
}
export function requestHostname(request: Request) {
  const url = new URL(request.url)
  return new URL(`${url.protocol}//${request.headers.get('host') || url.host}`)
    .hostname
}

export function apiBase(value: string | undefined, development: boolean) {
  const url = new URL(
    value ||
      (development ? 'http://127.0.0.1:8000' : 'https://missing.invalid'),
  )
  if (!value && !development)
    throw new GatewayError(
      503,
      'API_NOT_CONFIGURED',
      'The API connection is not configured.',
    )
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.protocol !== 'https:' &&
      !(url.protocol === 'http:' && isLoopbackHost(url.hostname)))
  ) {
    throw new GatewayError(
      503,
      'API_NOT_CONFIGURED',
      'The API URL must use HTTPS or a local development address.',
    )
  }
  return url.href.replace(/\/$/, '')
}

export function errorResponse(error: unknown) {
  const known = error instanceof GatewayError
  return Response.json(
    {
      error: {
        code: known ? error.code : 'GATEWAY_UNAVAILABLE',
        message: known
          ? error.message
          : 'The service could not be reached. Your change has not been confirmed.',
      },
    },
    {
      status: known ? error.status : 503,
      headers: { 'Cache-Control': 'no-store' },
    },
  )
}

export function operationKey(request: Request) {
  const key = request.headers.get('idempotency-key') || ''
  if (!/^[A-Za-z0-9_.:-]{8,128}$/.test(key))
    throw new GatewayError(
      422,
      'IDEMPOTENCY_KEY_REQUIRED',
      'A stable operation key is required.',
    )
  return key
}
