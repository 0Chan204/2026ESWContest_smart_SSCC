/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 'http' 면 실제 백엔드에 연결한다. 비어 있으면 목 데이터. */
  readonly VITE_DATA_SOURCE?: string
  /** 백엔드 오리진. 비우면 같은 주소(로컬은 Vite 프록시). 시크릿을 넣지 말 것. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
