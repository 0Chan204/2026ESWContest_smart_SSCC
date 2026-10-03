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

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), cspPlugin(buildCsp(loadEnv(mode, new URL('.', import.meta.url).pathname, 'VITE_').VITE_API_BASE_URL ?? ''))],
  resolve: {
    alias: {
      '@': new URL('./src', import.meta.url).pathname,
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
  },
  build: {
    target: 'es2022',
    sourcemap: false,
    chunkSizeWarningLimit: 700,
  },
}))
