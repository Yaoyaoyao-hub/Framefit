import type { Capabilities, Frame, Job, SearchResult, SessionDetail, SessionSummary } from "./types";

const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
let token = "";

export function mediaUrl(path: string | null | undefined) {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${base}${path}`;
}

export function setToken(value: string) {
  token = value;
}

async function parse<T>(response: Response): Promise<T> {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data?.error?.message || "Something went wrong. Try again.";
    throw new Error(message);
  }
  return data as T;
}

async function send<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("X-Workspace-Token", token);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${base}${path}`, { ...options, headers });
  return parse<T>(response);
}

export const api = {
  capabilities: () => send<Capabilities>("/api/capabilities"),
  createWorkspace: () => send<{ token: string; workspace_id: string }>("/api/workspaces", { method: "POST" }),
  sessions: () => send<{ sessions: SessionSummary[] }>("/api/photo-sessions"),
  session: (id: string) => send<SessionDetail>(`/api/photo-sessions/${id}`),
  uploadPhoto: (file: Blob, name = "photo.jpg") => {
    const body = new FormData();
    body.append("file", file, name);
    return send<SessionDetail>("/api/photo-sessions", { method: "POST", body });
  },
  uploadFrame: (sessionId: string, file: Blob, sourceKind: string, sourceUrl: string) => {
    const body = new FormData();
    body.append("file", file, "inspiration.jpg");
    body.append("source_kind", sourceKind);
    body.append("source_url", sourceUrl);
    return send<Frame>(`/api/photo-sessions/${sessionId}/inspiration-frames`, { method: "POST", body });
  },
  detect: (frameId: string) => send<Frame>(`/api/inspiration-frames/${frameId}/detect`, { method: "POST" }),
  createItem: (frameId: string, payload: { category: string; x: number; y: number; width: number; height: number }) =>
    send<Frame>(`/api/inspiration-frames/${frameId}/items`, { method: "POST", body: JSON.stringify(payload) }),
  updateItem: (itemId: string, payload: Record<string, string | number>) =>
    send<Frame>(`/api/items/${itemId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  tryOn: (sessionId: string, payload: Record<string, unknown>) =>
    send<Job>(`/api/photo-sessions/${sessionId}/try-on`, { method: "POST", body: JSON.stringify(payload) }),
  job: (id: string) => send<Job>(`/api/jobs/${id}`),
  activate: (sessionId: string, versionId: string) =>
    send<SessionDetail>(`/api/photo-sessions/${sessionId}/active`, { method: "POST", body: JSON.stringify({ version_id: versionId }) }),
  undo: (sessionId: string) => send<SessionDetail>(`/api/photo-sessions/${sessionId}/undo`, { method: "POST" }),
  reset: (sessionId: string) => send<SessionDetail>(`/api/photo-sessions/${sessionId}/reset`, { method: "POST" }),
  reload: (sessionId: string) => send<SessionDetail>(`/api/photo-sessions/${sessionId}/reload`, { method: "POST" }),
  acknowledge: (sessionId: string) => send<SessionDetail>(`/api/photo-sessions/${sessionId}/acknowledge-result`, { method: "POST" }),
  removeVersion: (versionId: string, subtree: boolean) =>
    send<SessionDetail>(`/api/versions/${versionId}?subtree=${subtree ? "true" : "false"}`, { method: "DELETE" }),
  removeSession: (sessionId: string) => send<{ deleted: boolean }>(`/api/photo-sessions/${sessionId}`, { method: "DELETE" }),
  search: (itemId: string) => send<{ source: string; demo_data: boolean; results: SearchResult[] }>(`/api/items/${itemId}/search`, { method: "POST" }),
  openVideo: async (url: string) => {
    const response = await fetch(`${base}/api/video-source`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Workspace-Token": token },
      body: JSON.stringify({ url }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data?.error?.message || "That video could not be opened.");
    }
    return response.blob();
  },
  sample: async (kind: "person" | "inspiration") => {
    const response = await fetch(`${base}/api/demo/samples/${kind}`, { headers: { "X-Workspace-Token": token } });
    if (!response.ok) throw new Error("That sample is not available.");
    return response.blob();
  },
};

export async function saveImage(url: string, filename: string) {
  const response = await fetch(mediaUrl(url));
  if (!response.ok) throw new Error("The image could not be downloaded.");
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(objectUrl);
}

let reloadClaimed = false;

export function claimReloadReset() {
  if (reloadClaimed) return false;
  reloadClaimed = true;
  const entry = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
  return entry?.type === "reload";
}
