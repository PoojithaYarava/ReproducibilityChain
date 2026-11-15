const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request(input: RequestInfo | URL, init?: RequestInit) {
  try {
    return await fetch(input, init);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new ApiError(
        "The workspace service is unavailable. Check your connection and try again.",
        0,
      );
    }
    throw error;
  }
}

export async function api<T>(
  path: string,
  token?: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await request(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === "string"
        ? body.detail
        : `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function download(
  path: string,
  token: string,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await request(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      typeof body?.detail === "string" ? body.detail : "Download failed",
      response.status,
    );
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const fileName = disposition.match(/filename="([^"]+)"/)?.[1] ?? "report.json";
  return { blob: await response.blob(), fileName };
}
