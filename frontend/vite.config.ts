import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 외부 CDN·트래커·유료 SDK를 일절 사용하지 않는다.
// 산출물은 정적 파일이며 어떤 백엔드에서도 그대로 서빙할 수 있다.

// 프로덕션 빌드 산출물에만 엄격한 CSP 를 주입한다.
// (dev 서버는 HMR 용 인라인 스크립트를 사용하므로 dev 에서는 적용하지 않는다)
function buildCsp(apiBase: string): string {
  // 백엔드 주소가 설정되면 그 출처(REST https + WebSocket wss)만 통신 허용에 추가한다.
  let api = ''
  try {
    if (apiBase) {
      const u = new URL(apiBase)
      api = ` ${u.origin} ${u.origin.replace(/^http/, 'ws')}`
    }
  } catch {
    throw new Error('VITE_API_BASE_URL 형식이 올바르지 않습니다: ' + apiBase)
  }
  return [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "form-action 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self'${api}`,
  "media-src 'self'",
  "worker-src 'self'",
  "manifest-src 'self'",
  ].join('; ')
}

function cspPlugin(csp: string) {
  return {
    name: 'homevis-csp',
    apply: 'build' as const,
    transformIndexHtml(html: string) {
      return html.replace(
        '<head>',
        `<head>\n    <meta http-equiv="Content-Security-Policy" content="${csp}" />`,
      )
    },
  }
}

// file:// URL → 파일 경로. Windows(/C:/… → C:/…)와 한글·공백 폴더명(%EC…)에서도 동작한다.
const toPath = (u: URL) => decodeURIComponent(u.pathname).replace(/^\/([A-Za-z]:)/, '$1')

/**
 * 로컬 백엔드 프록시. .env.local 에 HOMEVIS_API_TARGET=http://127.0.0.1:8000 을 두면
 * 개발 서버(5173)·미리보기(4173)가 /api 요청과 WebSocket(/api/v1/stream)을 그 주소로 넘긴다.
 * 브라우저는 같은 주소로만 통신하므로 백엔드에 CORS 를 열 필요가 없다.
 * (VITE_ 가 아니므로 이 값은 브라우저 번들에 들어가지 않는다)
 */
function apiProxy(target: string) {
  if (!target) return undefined
  let url: URL
  try {
    url = new URL(target)
  } catch {
    throw new Error('HOMEVIS_API_TARGET 형식이 올바르지 않습니다: ' + target)
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('HOMEVIS_API_TARGET 은 http(s) 주소여야 합니다.')
  return { '/api': { target: url.origin, ws: true, changeOrigin: false } }
}

export default defineConfig(({ mode }) => {
  const root = toPath(new URL('.', import.meta.url))
  const env = loadEnv(mode, root, '')
  const proxy = apiProxy(env.HOMEVIS_API_TARGET ?? '')
  return {
    plugins: [react(), tailwindcss(), cspPlugin(buildCsp(env.VITE_API_BASE_URL ?? ''))],
    resolve: {
      alias: {
        '@': toPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy,
    },
    preview: {
      host: '127.0.0.1',
      port: 4173,
      strictPort: true,
      proxy,
    },
    build: {
      target: 'es2022',
      sourcemap: false,
      chunkSizeWarningLimit: 700,
    },
  }
})
