/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 비어 있으면 목 데이터 소스를 사용한다. 시크릿을 넣지 말 것. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
