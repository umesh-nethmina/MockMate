export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// ---------- auth plumbing (set by AuthProvider) ----------

let authToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (!(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (authToken) headers.Authorization = `Bearer ${authToken}`;

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("Cannot reach the MockMate server. Check your connection and try again.", 0);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && authToken && !path.startsWith("/auth/")) onUnauthorized?.();
    throw new ApiError(body.error ?? `Request failed (${res.status})`, res.status);
  }
  return body as T;
}

// ---------- types ----------

export type Level = "intern" | "junior" | "mid";
export type SessionType = "full" | "hr" | "technical";
export type Personality = "friendly_hr" | "strict_tech_lead" | "fast_paced_founder";

export type User = { id: number; email: string | null; name: string; is_admin: boolean; is_guest: boolean };
export type TokenResponse = { access_token: string; expires_at: string; user: User };

export type Message = {
  id: number;
  speaker: "interviewer" | "candidate" | "system";
  kind: "question" | "follow_up" | "redirect" | "closing" | "answer" | "off_topic";
  round: string;
  topic: string | null;
  text: string;
  created_at: string;
};

export type Turn = {
  session_id: string;
  message: Message;
  done: boolean;
  questions_asked: number;
  question_limit: number;
};

export type SessionState = {
  id: string;
  role: string;
  level: Level;
  session_type: SessionType;
  personality: Personality;
  has_cv: boolean;
  job_description: string;
  status: "active" | "paused" | "completed";
  questions_asked: number;
  question_limit: number;
  started_at: string;
  has_report: boolean;
  messages: Message[];
};

export type SessionSummary = {
  id: string;
  role: string;
  level: Level;
  session_type: SessionType;
  status: string;
  questions_asked: number;
  question_limit: number;
  overall_score: number | null;
  started_at: string;
};

export type Star = { situation: boolean; task: boolean; action: boolean; result: boolean };

export type QuestionResult = {
  question: string;
  round: string;
  topic: string | null;
  answer: string;
  correctness: number;
  clarity: number;
  depth: number;
  average: number;
  star: Star | null;
  feedback: string;
  model_answer: string;
};

export type Report = {
  session_id: string;
  role: string;
  level: Level;
  session_type: SessionType;
  overall_score: number;
  strengths: string[];
  weaknesses: string[];
  summary: string;
  questions: QuestionResult[];
  total_tokens: number;
  cost_usd: number;
  created_at: string;
};

export type CV = { id: number; file_name: string; chars: number; truncated: boolean; preview: string; uploaded_at: string };

export type DayUsage = {
  date: string;
  cost_usd: number;
  calls: number;
  failed_calls: number;
  tokens: number;
  sessions: number;
  avg_cost_per_session: number | null;
};
export type Usage = {
  spent_today_usd: number;
  daily_cap_usd: number;
  days: DayUsage[];
  recent_sessions: {
    id: string;
    user_email: string | null;
    role: string;
    status: string;
    questions_asked: number;
    total_tokens: number;
    cost_usd: number;
  }[];
};

export type StartRequest = {
  role: string;
  level: Level;
  job_description: string;
  session_type: SessionType;
  personality: Personality;
  cv_id: number | null;
};

// ---------- endpoints ----------

const json = (body: unknown) => JSON.stringify(body);

export const register = (email: string, password: string, name: string) =>
  api<TokenResponse>("/auth/register", { method: "POST", body: json({ email, password, name }) });
export const login = (email: string, password: string) =>
  api<TokenResponse>("/auth/login", { method: "POST", body: json({ email, password }) });
export const loginAsGuest = () => api<TokenResponse>("/auth/guest", { method: "POST" });
export const getMe = () => api<User>("/users/me");
export const deleteAccount = (password: string) =>
  api<void>("/users/me", { method: "DELETE", body: json({ password }) });
export const mySessions = () => api<SessionSummary[]>("/users/me/sessions");

export const uploadCv = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api<CV>("/cv", { method: "POST", body: form });
};
export const listCvs = () => api<CV[]>("/cv");
export const deleteCv = (id: number) => api<void>(`/cv/${id}`, { method: "DELETE" });

export const startSession = (body: StartRequest) => api<Turn>("/sessions", { method: "POST", body: json(body) });
export const getSession = (id: string) => api<SessionState>(`/sessions/${id}`);
export const sendAnswer = (id: string, text: string) =>
  api<Turn>(`/sessions/${id}/answer`, { method: "POST", body: json({ text }) });
export const endSession = (id: string) => api<Report>(`/sessions/${id}/end`, { method: "POST" });
export const getReport = (id: string) => api<Report>(`/sessions/${id}/report`);
export const deleteSession = (id: string) => api<void>(`/sessions/${id}`, { method: "DELETE" });

export const getUsage = (days = 7) => api<Usage>(`/admin/usage?days=${days}`);
