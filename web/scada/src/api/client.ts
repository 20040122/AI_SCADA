const API_BASE = import.meta.env?.VITE_API_BASE_URL || "";
const API_TIMEOUT = 60000;

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

function isFormDataBody(body?: BodyInit | null): boolean {
  return typeof FormData !== "undefined" && body instanceof FormData;
}

async function request<T>(path: string, options?: RequestInit, timeoutMs?: number): Promise<T> {
  const url = `${API_BASE}${path}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs ?? API_TIMEOUT);

  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        ...(isFormDataBody(options?.body) ? {} : { "Content-Type": "application/json" }),
        ...options?.headers,
      },
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`API Error ${res.status}: ${text}`);
    }
    const json = await res.json();
    return json.data ?? json;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("请求超时，请稍后重试", { cause: err });
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export interface PostOptions {
  timeoutMs?: number;
}

export function post<T>(path: string, body: unknown, options?: PostOptions): Promise<T> {
  return request<T>(
    path,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
    options?.timeoutMs
  );
}

export function postForm<T>(path: string, body: FormData): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body,
  });
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}
