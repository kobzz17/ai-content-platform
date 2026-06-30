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
  importBatch: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/accounts/import-batch`, { method: "POST", body: form })
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(err.detail || "Import failed");
        }
        return res.json() as Promise<{ ok: Account[]; failed: { label: string; error: string }[] }>;
      });
  },

  importTdata: (file: File, passcode?: string, proxy?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (passcode) form.append("passcode", passcode);
    if (proxy) form.append("proxy", proxy);
    return fetch(`${BASE}/accounts/import-tdata`, { method: "POST", body: form })
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(err.detail || "Import failed");
        }
        return res.json() as Promise<{ ok: Account[]; failed: { label: string; error: string }[] }>;
      });
  },

  importAuthKeys: (accounts: { phone: string; auth_key_hex: string; dc_id: number; label?: string }[]) =>
    req<{ ok: Account[]; failed: { label: string; error: string }[] }>("/accounts/import-auth-keys", {
      method: "POST",
      body: JSON.stringify({ accounts }),
    }),

  importSessionFiles: (files: File[], proxy?: string) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    if (proxy) form.append("proxy", proxy);
    return fetch(`${BASE}/accounts/import-session-files`, { method: "POST", body: form })
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(err.detail || "Import failed");
        }
        return res.json() as Promise<{ ok: Account[]; failed: { label: string; error: string }[] }>;
      });
  },

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

  // Channel tasks
  listChannelTasks: () => req<ChannelTask[]>("/channels/tasks"),
  createChannelTask: (data: CreateChannelTaskPayload) =>
    req<ChannelTask>("/channels/tasks", { method: "POST", body: JSON.stringify(data) }),
  updateChannelTaskStatus: (taskId: number, status: TaskStatus) =>
    req<ChannelTask>(`/channels/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  triggerChannelTask: (taskId: number) =>
    req(`/channels/tasks/${taskId}/trigger`, { method: "POST" }),
  getChannelLogs: () => req<ChannelLog[]>("/channels/logs"),

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

  // Warmup
  listWarmupTasks: () => req<WarmupTask[]>("/warmup/tasks"),
  startWarmup: (account_id: number, target_days: number) =>
    req<WarmupTask>("/warmup/start", { method: "POST", body: JSON.stringify({ account_id, target_days }) }),
  pauseWarmup: (taskId: number) =>
    req(`/warmup/tasks/${taskId}/pause`, { method: "PATCH" }),
  resumeWarmup: (taskId: number) =>
    req(`/warmup/tasks/${taskId}/resume`, { method: "PATCH" }),
  stopWarmup: (taskId: number) =>
    req(`/warmup/tasks/${taskId}`, { method: "DELETE" }),
  getWarmupLogs: (accountId: number) =>
    req<WarmupLog[]>(`/warmup/logs/${accountId}`),
  getActivityFeed: (accountId?: number, limit = 100) =>
    req<ActivityEntry[]>(`/warmup/activity?limit=${limit}${accountId ? `&account_id=${accountId}` : ""}`),
  getAccountStats: () => req<AccountStats[]>("/warmup/stats"),
  getAccountEvents: () => req<AccountEvent[]>("/warmup/events"),
  setupProfiles: (account_ids: number[], gender: string, set_photo: boolean) =>
    req<object[]>("/warmup/setup-profiles", {
      method: "POST",
      body: JSON.stringify({ account_ids, gender, set_photo }),
    }),

  // Proxies
  listProxies: () => req<Proxy[]>("/proxies/"),
  addProxy: (data: AddProxyPayload) =>
    req<Proxy>("/proxies/", { method: "POST", body: JSON.stringify(data) }),
  addProxiesBatch: (proxies: string[]) =>
    req<{ added: number; failed: object[] }>("/proxies/batch", {
      method: "POST",
      body: JSON.stringify({ proxies }),
    }),
  assignProxy: (proxyId: number, account_id: number) =>
    req<Proxy>(`/proxies/${proxyId}/assign`, {
      method: "POST",
      body: JSON.stringify({ account_id }),
    }),
  autoAssignProxies: () => req("/proxies/auto-assign", { method: "POST" }),
  checkProxy: (proxyId: number) =>
    req<{ healthy: boolean; error: string | null }>(`/proxies/${proxyId}/check`, { method: "POST" }),
  deleteProxy: (proxyId: number) =>
    req(`/proxies/${proxyId}`, { method: "DELETE" }),

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

export type SessionMode = "always" | "random" | "work_hours" | "evening";

export interface ChannelTask {
  id: number;
  account_id: number;
  account_label: string | null;
  keywords: string;
  status: TaskStatus;
  persona: string;
  max_channels: number;
  comment_probability: number;
  reaction_probability: number;
  check_interval: number;
  max_daily_actions: number;
  session_mode: SessionMode;
  offline_until: string | null;
  subscriptions_count: number;
  last_run_at: string | null;
  created_at: string;
}

export interface ChannelLog {
  id: number;
  task_id: number;
  channel_title: string;
  action: string;
  text: string | null;
  created_at: string;
}

export interface CreateChannelTaskPayload {
  account_id: number;
  keywords: string;
  persona: string;
  max_channels: number;
  comment_probability: number;
  reaction_probability: number;
  check_interval: number;
  max_daily_actions: number;
  session_mode: string;
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

export type WarmupStatus = "pending" | "warming" | "completed" | "failed" | "paused";

export interface WarmupTask {
  id: number;
  account_id: number;
  account_label: string | null;
  account_phone: string | null;
  status: WarmupStatus;
  target_days: number;
  current_day: number;
  actions_today: number;
  actions_total: number;
  started_at: string | null;
  completed_at: string | null;
  last_activity_at: string | null;
  created_at: string;
}

export interface WarmupLog {
  id: number;
  account_id: number;
  action: string;
  detail: string | null;
  created_at: string;
}

export interface AccountStats {
  id: number;
  label: string;
  phone: string;
  status: string;
  warmup_status: string;
  warmup_started_at: string | null;
  total_actions: number;
  restrictions_count: number;
  bans_count: number;
  proxy: string | null;
  created_at: string;
}

export interface AccountEvent {
  id: number;
  account_id: number;
  event_type: string;
  detail: string | null;
  detected_at: string;
}

export interface ActivityEntry {
  source: "warmup" | "channel" | "group";
  account_id: number;
  action: string;
  detail: string | null;
  created_at: string;
}

export interface Proxy {
  id: number;
  protocol: string;
  host: string;
  port: number;
  username: string | null;
  is_active: boolean;
  is_healthy: boolean;
  last_checked_at: string | null;
  assigned_account_id: number | null;
  assigned_account_label: string | null;
  added_at: string;
}

export interface AddProxyPayload {
  protocol: string;
  host: string;
  port: number;
  username?: string;
  password?: string;
}
