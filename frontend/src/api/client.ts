const BASE = "http://localhost:8000/api";

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

export const api = {
  // Accounts
  listAccounts: () => req<Account[]>("/accounts/"),
  startAuth: (phone: string, label: string, proxy?: string) =>
    req("/accounts/auth/start", {
      method: "POST",
      body: JSON.stringify({ phone, label, proxy }),
    }),
  confirmAuth: (data: {
    phone: string; code: string; label: string;
    password?: string; proxy?: string;
  }) => req<Account>("/accounts/auth/confirm", { method: "POST", body: JSON.stringify(data) }),
  removeAccount: (id: number) =>
    req(`/accounts/${id}`, { method: "DELETE" }),

  // Dialogs & Messages
  getDialogs: (accountId: number) =>
    req<Dialog[]>(`/accounts/${accountId}/dialogs`),
  getMessages: (accountId: number, chatId: number) =>
    req<Message[]>(`/accounts/${accountId}/dialogs/${chatId}/messages`),
  sendMessage: (accountId: number, chatId: number, text: string) =>
    req(`/accounts/${accountId}/dialogs/${chatId}/send`, {
      method: "POST",
      body: JSON.stringify({ chat_id: chatId, text }),
    }),

  // Automation
  listTasks: () => req<BotTask[]>("/automation/tasks"),
  createTask: (data: CreateTaskPayload) =>
    req<BotTask>("/automation/tasks", { method: "POST", body: JSON.stringify(data) }),
  updateTaskStatus: (taskId: number, status: TaskStatus) =>
    req<BotTask>(`/automation/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  getTaskLogs: (taskId: number) => req<BotLog[]>(`/automation/tasks/${taskId}/logs`),
  getAllLogs: () => req<BotLog[]>("/automation/logs"),

  // AI
  suggest: (conversation: ConversationMessage[], hint?: string, tone?: string) =>
    req<{ suggestions: string[] }>("/ai/suggest", {
      method: "POST",
      body: JSON.stringify({ conversation, hint: hint ?? "", tone: tone ?? "friendly" }),
    }),
  improve: (text: string, instruction: string) =>
    req<{ result: string }>("/ai/improve", {
      method: "POST",
      body: JSON.stringify({ text, instruction }),
    }),
};

// ── Types ──────────────────────────────────────────────────────────────────

export interface Account {
  id: number;
  label: string;
  phone: string;
  username: string | null;
  first_name: string | null;
  avatar_color: string;
  status: "active" | "limited" | "needs_reauth" | "disabled";
  unread_count: number;
  is_active: boolean;
}

export interface Dialog {
  id: number;
  name: string;
  unread_count: number;
  last_message: string | null;
  last_message_date: string | null;
  is_group: boolean;
}

export interface Message {
  id: number;
  sender: string;
  text: string;
  date: string;
  is_outgoing: boolean;
}

export interface ConversationMessage {
  sender: string;
  text: string;
}

export type TaskStatus = "running" | "paused" | "stopped";

export interface BotTask {
  id: number;
  account_id: number;
  account_label: string | null;
  chat_id: number;
  chat_name: string;
  status: TaskStatus;
  persona: string;
  reply_probability: number;
  min_delay: number;
  max_delay: number;
  proactive_interval: number | null;
  last_action_at: string | null;
  created_at: string;
}

export interface BotLog {
  id: number;
  task_id: number;
  action: string;
  text: string | null;
  created_at: string;
}

export interface CreateTaskPayload {
  account_id: number;
  chat_id: number;
  chat_name: string;
  persona: string;
  reply_probability: number;
  min_delay: number;
  max_delay: number;
  proactive_interval: number | null;
}
