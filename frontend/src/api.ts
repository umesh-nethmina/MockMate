export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Cannot reach the MockMate server. Check your connection and try again.", 0);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(body.error ?? `Request failed (${res.status})`, res.status);
  return body as T;
}

export type Level = "intern" | "junior" | "mid";

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
  job_description: string;
  status: "active" | "paused" | "completed";
  questions_asked: number;
  question_limit: number;
  started_at: string;
  has_report: boolean;
  messages: Message[];
};

export type QuestionResult = {
  question: string;
  topic: string | null;
  answer: string;
  correctness: number;
  clarity: number;
  depth: number;
  average: number;
  feedback: string;
  model_answer: string;
};

export type Report = {
  session_id: string;
  role: string;
  level: Level;
  overall_score: number;
  strengths: string[];
  weaknesses: string[];
  summary: string;
  questions: QuestionResult[];
  total_tokens: number;
  cost_usd: number;
  created_at: string;
};

export type StartRequest = { role: string; level: Level; job_description: string };

export const startSession = (body: StartRequest) =>
  api<Turn>("/sessions", { method: "POST", body: JSON.stringify(body) });

export const getSession = (id: string) => api<SessionState>(`/sessions/${id}`);

export const sendAnswer = (id: string, text: string) =>
  api<Turn>(`/sessions/${id}/answer`, { method: "POST", body: JSON.stringify({ text }) });

export const endSession = (id: string) => api<Report>(`/sessions/${id}/end`, { method: "POST" });

export const getReport = (id: string) => api<Report>(`/sessions/${id}/report`);

export const getHealth = () => api<{ status: string }>("/health");
