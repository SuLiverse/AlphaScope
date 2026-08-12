/**
 * Base API module for the 研策中枢 AlphaScope frontend.
 */

const runtimeConfig = typeof window !== 'undefined' ? window.__ALPHASCOPE_CONFIG__ : undefined;

// Runtime config is written by the packaged desktop launcher. Vite env remains
// the development and Docker fallback.
export const API_BASE_URL = runtimeConfig?.apiBaseUrl || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export const API_KEY = runtimeConfig?.apiKey || import.meta.env.VITE_API_KEY || '';

/**
 * Token 解析纯函数（node 环境可单测）。优先级：运行时配置 > sessionStorage > Vite env。
 * docker 部署下共享卷副本不再携带 token，远程用户经引导页输入一次，
 * storeLocalToken 写入 sessionStorage（关页即清）。
 */
export function resolveLocalToken(cfg?: string, stored?: string, env?: string): string {
  return cfg || stored || env || '';
}

const storedLocalToken =
  typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('alphascope.localToken') ?? undefined : undefined;

// 模块加载期以 const 固化会锁死引导页输入后的新 token；用 export let 保持 ESM
// live binding，storeLocalToken 刷新后所有引用点（含 query/header 发送方）同步生效。
export let LOCAL_API_TOKEN = resolveLocalToken(
  runtimeConfig?.localApiToken,
  storedLocalToken,
  import.meta.env.VITE_LOCAL_API_TOKEN,
);

export function storeLocalToken(token: string): void {
  LOCAL_API_TOKEN = token;
  if (typeof sessionStorage !== 'undefined') {
    sessionStorage.setItem('alphascope.localToken', token);
  }
}

export class ApiRequestError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
  }
}

export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

export async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
  const headers = new Headers(options?.headers);
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (API_KEY && !headers.has('X-API-Key') && !headers.has('Authorization')) {
    headers.set('X-API-Key', API_KEY);
  }
  if (LOCAL_API_TOKEN && !headers.has('X-AlphaScope-Local-Token')) {
    headers.set('X-AlphaScope-Local-Token', LOCAL_API_TOKEN);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new ApiRequestError(
      `API Request Failed: ${response.status} ${response.statusText} - ${errorText}`,
      response.status,
    );
  }

  const result: ApiResponse<T> = await response.json();
  if (!result.success) {
    throw new Error(result.error || 'API Request Failed with unknown error');
  }

  return result.data as T;
}
