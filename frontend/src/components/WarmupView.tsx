import { useState, useEffect } from "react";
import { api, WarmupTask, WarmupLog, AccountStats, AccountEvent, Account, ActivityEntry } from "../api/client";

interface Props {
  accounts: Account[];
}

type Tab = "tasks" | "monitoring" | "events" | "activity";

const STATUS_COLORS: Record<string, string> = {
  warming: "#3b82f6",
  completed: "#22c55e",
  failed: "#ef4444",
  paused: "#f59e0b",
  pending: "#94a3b8",
};

const STATUS_LABELS: Record<string, string> = {
  warming: "Прогрев",
  completed: "Завершён",
  failed: "Ошибка",
  paused: "Пауза",
  pending: "Ожидание",
};

const EVENT_ICONS: Record<string, string> = {
  ban: "🚫",
  restriction: "⚠️",
  flood_wait: "⏳",
  checkpoint: "🔐",
  warning: "⚡",
};

const ACTIVITY_ICONS: Record<string, string> = {
  joined_channel: "📢", subscribe: "📢", subscribed: "📢",
  read_messages: "👁", reacted: "👍", commented: "💬",
  reply: "💬", topic: "🗣", news: "📰", react: "❤",
  sent_message: "📨", profile_setup: "🔧", set_username: "🔧",
  set_name: "🔧", set_photo: "📷",
};

const ACTIVITY_LABELS: Record<string, string> = {
  joined_channel: "Подписался на канал", subscribe: "Подписался",
  subscribed: "Подписался на канал",
  read_messages: "Прочитал сообщения", reacted: "Поставил реакцию",
  commented: "Написал комментарий",
  reply: "Ответил в группе", topic: "Начал тему", news: "Поделился новостью",
  react: "Реакция в группе", sent_message: "Отправил сообщение",
  profile_setup: "Настройка профиля", set_username: "Установил юзернейм",
  set_name: "Установил имя", set_photo: "Загрузил фото",
};

const SOURCE_COLORS: Record<string, string> = {
  warmup: "#3b82f6",
  channel: "#10b981",
  group: "#a78bfa",
};

export default function WarmupView({ accounts }: Props) {
  const [tab, setTab] = useState<Tab>("tasks");
  const [tasks, setTasks] = useState<WarmupTask[]>([]);
  const [stats, setStats] = useState<AccountStats[]>([]);
  const [events, setEvents] = useState<AccountEvent[]>([]);
  const [logs, setLogs] = useState<WarmupLog[]>([]);
  const [logsAccountId, setLogsAccountId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [activityAccountId, setActivityAccountId] = useState<number | undefined>(undefined);

  // Start warmup form
  const [showStart, setShowStart] = useState(false);
  const [startAccountId, setStartAccountId] = useState<number | null>(null);
  const [startDays, setStartDays] = useState(7);
  const [profileSetup, setProfileSetup] = useState(false);
  const [gender, setGender] = useState("random");
  const [startError, setStartError] = useState("");

  // Proxy setup
  const [batchText, setBatchText] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      if (tab === "tasks") {
        setTasks(await api.listWarmupTasks());
      } else if (tab === "monitoring") {
        setStats(await api.getAccountStats());
      } else if (tab === "events") {
        setEvents(await api.getAccountEvents());
      } else if (tab === "activity") {
        setActivity(await api.getActivityFeed(activityAccountId, 150));
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, [tab, activityAccountId]);

  const startWarmup = async () => {
    if (!startAccountId) return;
    setStartError("");
    try {
      if (profileSetup) {
        await api.setupProfiles([startAccountId], gender, true);
      }
      await api.startWarmup(startAccountId, startDays);
      setShowStart(false);
      load();
    } catch (e: unknown) {
      setStartError(e instanceof Error ? e.message : "Ошибка");
    }
  };

  const loadLogs = async (accountId: number) => {
    setLogsAccountId(accountId);
    const data = await api.getWarmupLogs(accountId);
    setLogs(data);
  };

  const accountsWithoutWarmup = accounts.filter(
    (a) => a.is_active && !tasks.find(
      (t) => t.account_id === a.id && ["warming", "pending", "paused"].includes(t.status)
    )
  );

  return (
    <div style={{ padding: "20px", color: "#e2e8f0", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>Прогрев аккаунтов</h2>
        <button
          onClick={() => setShowStart(true)}
          style={{
            background: "#3b82f6", color: "#fff", border: "none",
            borderRadius: 6, padding: "8px 16px", cursor: "pointer",
          }}
        >
          + Запустить прогрев
        </button>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {(["tasks", "monitoring", "activity", "events"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: "6px 16px", borderRadius: 6, border: "none", cursor: "pointer",
              background: tab === t ? "#334155" : "#1e293b",
              color: tab === t ? "#fff" : "#94a3b8",
              fontWeight: tab === t ? 600 : 400,
            }}
          >
            {t === "tasks" ? "Задачи" : t === "monitoring" ? "Статистика" : t === "activity" ? "Активность" : "События"}
          </button>
        ))}
        <button onClick={load} style={{
          marginLeft: "auto", padding: "6px 12px", borderRadius: 6,
          border: "1px solid #334155", background: "transparent",
          color: "#94a3b8", cursor: "pointer",
        }}>↻</button>
      </div>

      {loading && <div style={{ color: "#94a3b8" }}>Загрузка...</div>}

      {/* TASKS TAB */}
      {tab === "tasks" && !loading && (
        <div>
          {tasks.length === 0 && (
            <div style={{ color: "#64748b", textAlign: "center", marginTop: 40 }}>
              Нет активных задач прогрева
            </div>
          )}
          {tasks.map((task) => (
            <div
              key={task.id}
              style={{
                background: "#1e293b", borderRadius: 8, padding: 16,
                marginBottom: 12, border: "1px solid #334155",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 15 }}>
                    {task.account_label || `Аккаунт #${task.account_id}`}
                  </div>
                  <div style={{ color: "#94a3b8", fontSize: 13, marginTop: 2 }}>
                    {task.account_phone}
                  </div>
                </div>
                <span style={{
                  background: STATUS_COLORS[task.status] + "22",
                  color: STATUS_COLORS[task.status],
                  borderRadius: 4, padding: "2px 10px", fontSize: 12, fontWeight: 600,
                }}>
                  {STATUS_LABELS[task.status]}
                </span>
              </div>

              {/* Progress bar */}
              <div style={{ marginTop: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#94a3b8", marginBottom: 4 }}>
                  <span>День {task.current_day} из {task.target_days}</span>
                  <span>{task.actions_total} действий всего</span>
                </div>
                <div style={{ background: "#334155", borderRadius: 4, height: 6, overflow: "hidden" }}>
                  <div style={{
                    width: `${Math.min((task.current_day / task.target_days) * 100, 100)}%`,
                    background: STATUS_COLORS[task.status],
                    height: "100%", borderRadius: 4, transition: "width 0.3s",
                  }} />
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                {task.status === "warming" && (
                  <button
                    onClick={async () => { await api.pauseWarmup(task.id); load(); }}
                    style={{ padding: "4px 12px", borderRadius: 4, border: "none", background: "#f59e0b22", color: "#f59e0b", cursor: "pointer", fontSize: 12 }}
                  >Пауза</button>
                )}
                {task.status === "paused" && (
                  <button
                    onClick={async () => { await api.resumeWarmup(task.id); load(); }}
                    style={{ padding: "4px 12px", borderRadius: 4, border: "none", background: "#3b82f622", color: "#3b82f6", cursor: "pointer", fontSize: 12 }}
                  >Возобновить</button>
                )}
                {["warming", "paused", "pending"].includes(task.status) && (
                  <button
                    onClick={async () => { await api.stopWarmup(task.id); load(); }}
                    style={{ padding: "4px 12px", borderRadius: 4, border: "none", background: "#ef444422", color: "#ef4444", cursor: "pointer", fontSize: 12 }}
                  >Остановить</button>
                )}
                <button
                  onClick={() => loadLogs(task.account_id)}
                  style={{ padding: "4px 12px", borderRadius: 4, border: "none", background: "#334155", color: "#e2e8f0", cursor: "pointer", fontSize: 12 }}
                >Логи</button>
              </div>
            </div>
          ))}

          {/* Logs panel */}
          {logsAccountId && (
            <div style={{ background: "#0f172a", borderRadius: 8, padding: 16, marginTop: 16, border: "1px solid #334155" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                <strong>Логи аккаунта #{logsAccountId}</strong>
                <button onClick={() => setLogsAccountId(null)} style={{ background: "none", border: "none", color: "#94a3b8", cursor: "pointer" }}>✕</button>
              </div>
              {logs.length === 0 && <div style={{ color: "#64748b" }}>Нет логов</div>}
              {logs.map((l) => (
                <div key={l.id} style={{ fontSize: 12, padding: "4px 0", borderBottom: "1px solid #1e293b", display: "flex", gap: 12 }}>
                  <span style={{ color: "#64748b", minWidth: 140 }}>
                    {new Date(l.created_at).toLocaleString("ru")}
                  </span>
                  <span style={{ color: "#60a5fa" }}>{l.action}</span>
                  <span style={{ color: "#94a3b8" }}>{l.detail}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* MONITORING TAB */}
      {tab === "monitoring" && !loading && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 }}>
            {stats.map((s) => (
              <div key={s.id} style={{
                background: "#1e293b", borderRadius: 8, padding: 14,
                border: `1px solid ${s.bans_count > 0 ? "#ef444440" : "#334155"}`,
              }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>{s.label}</div>
                <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>{s.phone}</div>
                <div style={{ fontSize: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
                  <span style={{ color: "#64748b" }}>Прогрев:</span>
                  <span style={{ color: s.warmup_status === "warmed" ? "#22c55e" : s.warmup_status === "warming" ? "#3b82f6" : "#94a3b8" }}>
                    {s.warmup_status}
                  </span>
                  <span style={{ color: "#64748b" }}>Действий:</span>
                  <span>{s.total_actions}</span>
                  <span style={{ color: "#64748b" }}>Ограничений:</span>
                  <span style={{ color: s.restrictions_count > 0 ? "#f59e0b" : "#94a3b8" }}>{s.restrictions_count}</span>
                  <span style={{ color: "#64748b" }}>Банов:</span>
                  <span style={{ color: s.bans_count > 0 ? "#ef4444" : "#94a3b8" }}>{s.bans_count}</span>
                  {s.proxy && (
                    <>
                      <span style={{ color: "#64748b" }}>Прокси:</span>
                      <span style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {s.proxy.replace(/^.*@/, "").replace(/^socks5:\/\//, "")}
                      </span>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
          {stats.length === 0 && (
            <div style={{ color: "#64748b", textAlign: "center", marginTop: 40 }}>Нет активных аккаунтов</div>
          )}
        </div>
      )}

      {/* EVENTS TAB */}
      {tab === "events" && !loading && (
        <div>
          {events.length === 0 && (
            <div style={{ color: "#64748b", textAlign: "center", marginTop: 40 }}>Событий не зафиксировано</div>
          )}
          {events.map((e) => (
            <div key={e.id} style={{
              background: "#1e293b", borderRadius: 6, padding: "10px 14px",
              marginBottom: 8, border: "1px solid #334155",
              display: "flex", gap: 12, alignItems: "flex-start",
            }}>
              <span style={{ fontSize: 18 }}>{EVENT_ICONS[e.event_type] || "ℹ️"}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>
                  Аккаунт #{e.account_id} — {e.event_type}
                </div>
                {e.detail && <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>{e.detail}</div>}
              </div>
              <div style={{ fontSize: 11, color: "#64748b", whiteSpace: "nowrap" }}>
                {new Date(e.detected_at).toLocaleString("ru")}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ACTIVITY TAB */}
      {tab === "activity" && !loading && (
        <div>
          {/* Account filter */}
          <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: "#94a3b8", fontSize: 13 }}>Фильтр по аккаунту:</span>
            <select
              value={activityAccountId ?? ""}
              onChange={(e) => setActivityAccountId(e.target.value ? Number(e.target.value) : undefined)}
              style={{
                background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155",
                borderRadius: 6, padding: "4px 10px", fontSize: 13,
              }}
            >
              <option value="">Все аккаунты</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.label} ({a.phone})</option>
              ))}
            </select>
          </div>

          {activity.length === 0 && (
            <div style={{ color: "#64748b", textAlign: "center", marginTop: 40 }}>
              Активности пока нет — аккаунты только начали работу
            </div>
          )}

          {activity.map((entry, i) => {
            const account = accounts.find((a) => a.id === entry.account_id);
            const icon = ACTIVITY_ICONS[entry.action] || "•";
            const label = ACTIVITY_LABELS[entry.action] || entry.action;
            const color = SOURCE_COLORS[entry.source] || "#64748b";
            return (
              <div key={i} style={{
                background: "#1e293b", borderRadius: 6, padding: "10px 14px",
                marginBottom: 6, border: "1px solid #334155",
                display: "flex", gap: 12, alignItems: "flex-start",
              }}>
                <span style={{ fontSize: 16, minWidth: 20 }}>{icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{
                      fontSize: 11, fontWeight: 600, padding: "1px 7px",
                      borderRadius: 4, background: color + "22", color,
                    }}>
                      {entry.source === "warmup" ? "Прогрев" : entry.source === "channel" ? "Канал" : "Группа"}
                    </span>
                    <span style={{ fontSize: 12, color: "#cbd5e1", fontWeight: 500 }}>{label}</span>
                    {account && (
                      <span style={{ fontSize: 11, color: "#64748b" }}>
                        — {(account as any).label || (account as any).first_name || `#${entry.account_id}`}
                      </span>
                    )}
                  </div>
                  {entry.detail && (
                    <div style={{
                      fontSize: 12, color: "#94a3b8", marginTop: 3,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {entry.detail}
                    </div>
                  )}
                </div>
                <div style={{ fontSize: 11, color: "#64748b", whiteSpace: "nowrap", flexShrink: 0 }}>
                  {new Date(entry.created_at).toLocaleString("ru", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Start Warmup Modal */}
      {showStart && (
        <div style={{
          position: "fixed", inset: 0, background: "#00000099",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
        }}>
          <div style={{
            background: "#1e293b", borderRadius: 12, padding: 24,
            width: 380, border: "1px solid #334155",
          }}>
            <h3 style={{ margin: "0 0 16px" }}>Запустить прогрев</h3>

            <label style={{ display: "block", marginBottom: 12 }}>
              <span style={{ color: "#94a3b8", fontSize: 13 }}>Аккаунт</span>
              <select
                value={startAccountId ?? ""}
                onChange={(e) => setStartAccountId(Number(e.target.value))}
                style={{
                  display: "block", width: "100%", marginTop: 4,
                  background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155",
                  borderRadius: 6, padding: "8px 10px",
                }}
              >
                <option value="">— выбрать —</option>
                {accountsWithoutWarmup.map((a) => (
                  <option key={a.id} value={a.id}>{a.label} ({a.phone})</option>
                ))}
              </select>
            </label>

            <label style={{ display: "block", marginBottom: 12 }}>
              <span style={{ color: "#94a3b8", fontSize: 13 }}>Длительность (дней): {startDays}</span>
              <input
                type="range" min={3} max={14} value={startDays}
                onChange={(e) => setStartDays(Number(e.target.value))}
                style={{ display: "block", width: "100%", marginTop: 4 }}
              />
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#64748b" }}>
                <span>3</span><span>7</span><span>14</span>
              </div>
            </label>

            <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, cursor: "pointer" }}>
              <input type="checkbox" checked={profileSetup} onChange={(e) => setProfileSetup(e.target.checked)} />
              <span style={{ fontSize: 13, color: "#94a3b8" }}>Настроить профиль перед прогревом</span>
            </label>

            {profileSetup && (
              <label style={{ display: "block", marginBottom: 12 }}>
                <span style={{ color: "#94a3b8", fontSize: 13 }}>Пол</span>
                <select
                  value={gender}
                  onChange={(e) => setGender(e.target.value)}
                  style={{
                    display: "block", width: "100%", marginTop: 4,
                    background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155",
                    borderRadius: 6, padding: "8px 10px",
                  }}
                >
                  <option value="random">Случайный</option>
                  <option value="male">Мужской</option>
                  <option value="female">Женский</option>
                </select>
              </label>
            )}

            {startError && (
              <div style={{ color: "#ef4444", fontSize: 13, marginBottom: 12 }}>{startError}</div>
            )}

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button
                onClick={() => setShowStart(false)}
                style={{ padding: "8px 16px", borderRadius: 6, border: "1px solid #334155", background: "transparent", color: "#94a3b8", cursor: "pointer" }}
              >Отмена</button>
              <button
                onClick={startWarmup}
                disabled={!startAccountId}
                style={{
                  padding: "8px 16px", borderRadius: 6, border: "none",
                  background: startAccountId ? "#3b82f6" : "#334155",
                  color: "#fff", cursor: startAccountId ? "pointer" : "default",
                }}
              >Запустить</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
