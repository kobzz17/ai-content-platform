import { useEffect, useRef, useState } from "react";
import { api, Account, BotTask, BotLog, Dialog, CreateTaskPayload, ChannelTask, ChannelLog, CreateChannelTaskPayload, SessionMode, BoostTask, BoostLog } from "../api/client";

const SESSION_MODE_LABELS: Record<SessionMode, string> = {
  always: "Всегда активен",
  random: "Хаотичный режим",
  work_hours: "Рабочие часы (9-20 UTC)",
  evening: "Вечерний (18-23 UTC)",
};

interface Props {
  accounts: Account[];
}

const ACTION_LABELS: Record<string, string> = {
  replied: "Ответил",
  topic_posted: "Новая тема",
  error: "Ошибка",
};

const STATUS_BADGE: Record<string, { label: string; color: string }> = {
  running: { label: "Работает", color: "#22c55e" },
  paused: { label: "Пауза", color: "#f59e0b" },
  stopped: { label: "Остановлен", color: "#6b7280" },
};

type MainTab = "chats" | "channels" | "boost";

const CH_ACTION_LABELS: Record<string, string> = {
  subscribed: "Подписался",
  commented: "Прокомментировал",
  reacted: "Реакция",
  error: "Ошибка",
};

export function AutomationView({ accounts }: Props) {
  const [mainTab, setMainTab] = useState<MainTab>("chats");
  const [tasks, setTasks] = useState<BotTask[]>([]);
  const [logs, setLogs] = useState<BotLog[]>([]);
  const [channelTasks, setChannelTasks] = useState<ChannelTask[]>([]);
  const [channelLogs, setChannelLogs] = useState<ChannelLog[]>([]);
  const [boosts, setBoosts] = useState<BoostTask[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [showChannelModal, setShowChannelModal] = useState(false);
  const [showBoostModal, setShowBoostModal] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadTasks();
    loadLogs();
    loadChannelTasks();
    loadChannelLogs();
    loadBoosts();
    const interval = setInterval(() => {
      loadTasks();
      loadLogs();
      loadChannelTasks();
      loadChannelLogs();
      loadBoosts();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  async function loadTasks() {
    try {
      setTasks(await api.listTasks());
    } catch {}
  }

  async function loadLogs() {
    try { setLogs(await api.getAllLogs()); } catch {}
  }

  async function loadChannelTasks() {
    try { setChannelTasks(await api.listChannelTasks()); } catch {}
  }

  async function loadChannelLogs() {
    try { setChannelLogs(await api.getChannelLogs()); } catch {}
  }

  async function loadBoosts() {
    try { setBoosts(await api.listBoosts()); } catch {}
  }

  async function handleStatus(task: BotTask, status: "running" | "paused" | "stopped") {
    try {
      const updated = await api.updateTaskStatus(task.id, status);
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      if (status === "stopped") {
        setTasks((prev) => prev.filter((t) => t.id !== updated.id));
      }
    } catch {}
  }

  async function handleTaskCreated(task: BotTask) {
    setTasks((prev) => [task, ...prev]);
    setShowModal(false);
  }

  async function handleChannelStatus(task: ChannelTask, status: "running" | "paused" | "stopped") {
    try {
      const updated = await api.updateChannelTaskStatus(task.id, status);
      if (status === "stopped") setChannelTasks(prev => prev.filter(t => t.id !== updated.id));
      else setChannelTasks(prev => prev.map(t => t.id === updated.id ? updated : t));
    } catch {}
  }

  async function handleTriggerNow(taskId: number) {
    try {
      await api.triggerChannelTask(taskId);
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <div style={s.root}>
      <div style={s.header}>
        <div style={s.headerLeft}>
          <span style={s.title}>Автоматизация</span>
          <div style={s.mainTabs}>
            <button style={{...s.mainTab, ...(mainTab === "chats" ? s.mainTabActive : {})}} onClick={() => setMainTab("chats")}>💬 Чаты</button>
            <button style={{...s.mainTab, ...(mainTab === "channels" ? s.mainTabActive : {})}} onClick={() => setMainTab("channels")}>📡 Каналы</button>
            <button style={{...s.mainTab, ...(mainTab === "boost" ? s.mainTabActive : {})}} onClick={() => setMainTab("boost")}>🚀 Буст поста</button>
          </div>
        </div>
        {mainTab === "chats" && <button style={s.addBtn} onClick={() => setShowModal(true)}>+ Добавить задачу</button>}
        {mainTab === "channels" && <button style={s.addBtn} onClick={() => setShowChannelModal(true)}>+ Мониторинг канала</button>}
        {mainTab === "boost" && <button style={{...s.addBtn, background: "#7c3aed"}} onClick={() => setShowBoostModal(true)}>🚀 Запустить буст</button>}
      </div>

      <div style={s.body}>
        {mainTab === "channels" && (
          <>
            <div style={s.taskPanel}>
              <div style={s.panelTitle}>Мониторинг каналов</div>
              {channelTasks.length === 0 && <div style={s.empty}>Нет активных задач</div>}
              {channelTasks.map(ct => {
                const badge = STATUS_BADGE[ct.status] || STATUS_BADGE.stopped;
                return (
                  <div key={ct.id} style={s.taskCard}>
                    <div style={s.taskRow}>
                      <span style={s.taskAccount}>{ct.account_label || `#${ct.account_id}`}</span>
                      <span style={{...s.taskBadge, color: badge.color, borderColor: badge.color}}>{badge.label}</span>
                    </div>
                    <div style={s.taskChat}>🔍 {ct.keywords}</div>
                    <div style={s.taskMeta}>
                      Подписок: {ct.subscriptions_count}/{ct.max_channels} · Комментарии: {ct.comment_probability}% · Реакции: {ct.reaction_probability}%
                    </div>
                    <div style={s.taskMeta}>
                      Проверка каждые {ct.check_interval} мин · Макс {ct.max_daily_actions} действий/день
                    </div>
                    {ct.last_run_at && <div style={s.taskMeta}>Последняя проверка: {new Date(ct.last_run_at).toLocaleTimeString("ru-RU", {hour:"2-digit",minute:"2-digit"})}</div>}
                    <div style={s.taskMeta}>
                      Режим: <span style={{color: ct.session_mode === "always" ? "#22c55e" : ct.session_mode === "random" ? "#a78bfa" : "#f59e0b"}}>
                        {SESSION_MODE_LABELS[ct.session_mode] || ct.session_mode}
                      </span>
                    </div>
                    {ct.offline_until && new Date(ct.offline_until) > new Date() && (
                      <div style={{...s.taskMeta, color: "#f59e0b"}}>
                        😴 Оффлайн до {new Date(ct.offline_until).toLocaleTimeString("ru-RU", {hour:"2-digit",minute:"2-digit"})}
                      </div>
                    )}
                    <div style={s.taskActions}>
                      {ct.status === "running" && (
                        <>
                          <button style={s.btnTrigger} onClick={() => handleTriggerNow(ct.id)}>⚡ Проверить сейчас</button>
                          <button style={s.btnPause} onClick={() => handleChannelStatus(ct, "paused")}>⏸ Пауза</button>
                        </>
                      )}
                      {ct.status === "paused" && <button style={s.btnPlay} onClick={() => handleChannelStatus(ct, "running")}>▶ Запустить</button>}
                      <button style={s.btnStop} onClick={() => handleChannelStatus(ct, "stopped")}>⛔ Стоп</button>
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={s.logPanel}>
              <div style={s.panelTitle}>Лог активности в каналах</div>
              <div style={s.logList}>
                {channelLogs.length === 0 && <div style={s.empty}>Действий пока нет</div>}
                {[...channelLogs].reverse().map(log => {
                  const label = CH_ACTION_LABELS[log.action] || log.action;
                  const time = new Date(log.created_at).toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
                  const isError = log.action === "error";
                  const actionColor = log.action === "subscribed" ? "#22c55e" : log.action === "commented" ? "#60a5fa" : log.action === "reacted" ? "#f59e0b" : "#ef4444";
                  return (
                    <div key={log.id} style={{...s.logItem, ...(isError ? s.logError : {})}}>
                      <span style={s.logTime}>{time}</span>
                      <span style={s.logAccount}>[{log.channel_title}]</span>
                      <span style={{...s.logAction, color: actionColor}}>{label}</span>
                      {log.text && <span style={s.logText}>"{log.text}"</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}

        {mainTab === "chats" && <>
        {/* Task list */}
        <div style={s.taskPanel}>
          <div style={s.panelTitle}>Активные задачи</div>
          {tasks.length === 0 && (
            <div style={s.empty}>Нет активных задач</div>
          )}
          {tasks.map((task) => {
            const badge = STATUS_BADGE[task.status] || STATUS_BADGE.stopped;
            const lastAction = task.last_action_at
              ? new Date(task.last_action_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
              : "—";
            return (
              <div key={task.id} style={s.taskCard}>
                <div style={s.taskRow}>
                  <span style={s.taskAccount}>{task.account_label || `#${task.account_id}`}</span>
                  <span style={{ ...s.taskBadge, color: badge.color, borderColor: badge.color }}>
                    {badge.label}
                  </span>
                </div>
                <div style={s.taskChat}>💬 {task.chat_name}</div>
                <div style={s.taskMeta}>
                  Вероятность ответа: {task.reply_probability}% · Задержка: {task.min_delay}–{task.max_delay}с
                  {task.proactive_interval ? ` · Тема каждые ${task.proactive_interval} мин` : ""}
                </div>
                <div style={s.taskMeta}>Последнее действие: {lastAction}</div>
                <div style={s.taskActions}>
                  {task.status === "running" && (
                    <button style={s.btnPause} onClick={() => handleStatus(task, "paused")}>⏸ Пауза</button>
                  )}
                  {task.status === "paused" && (
                    <button style={s.btnPlay} onClick={() => handleStatus(task, "running")}>▶ Запустить</button>
                  )}
                  <button style={s.btnStop} onClick={() => handleStatus(task, "stopped")}>⛔ Стоп</button>
                </div>
              </div>
            );
          })}
        </div>

        {/* Activity log */}
        <div style={s.logPanel}>
          <div style={s.panelTitle}>Лог активности</div>
          <div style={s.logList}>
            {logs.length === 0 && <div style={s.empty}>Действий пока нет</div>}
            {[...logs].reverse().map((log) => {
              const task = tasks.find((t) => t.id === log.task_id);
              const label = ACTION_LABELS[log.action] || log.action;
              const time = new Date(log.created_at).toLocaleTimeString("ru-RU", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              });
              const isError = log.action === "error";
              return (
                <div key={log.id} style={{ ...s.logItem, ...(isError ? s.logError : {}) }}>
                  <span style={s.logTime}>{time}</span>
                  <span style={s.logAccount}>[{task?.account_label || `задача #${log.task_id}`}]</span>
                  <span style={{ ...s.logAction, color: isError ? "#ef4444" : log.action === "topic_posted" ? "#a78bfa" : "#60a5fa" }}>
                    {label}
                  </span>
                  {log.text && <span style={s.logText}>"{log.text}"</span>}
                </div>
              );
            })}
            <div ref={logsEndRef} />
          </div>
        </div>
        </>}

        {mainTab === "boost" && (
          <BoostPanel
            boosts={boosts}
            onCancel={async (id) => {
              try { await api.cancelBoost(id); loadBoosts(); } catch {}
            }}
          />
        )}
      </div>

      {showModal && (
        <AddTaskModal
          accounts={accounts}
          onCreated={handleTaskCreated}
          onClose={() => setShowModal(false)}
        />
      )}

      {showChannelModal && (
        <AddChannelTaskModal
          accounts={accounts}
          onCreated={(ct) => { setChannelTasks(prev => [ct, ...prev]); setShowChannelModal(false); }}
          onClose={() => setShowChannelModal(false)}
        />
      )}

      {showBoostModal && (
        <BoostModal
          onCreated={(b) => { setBoosts(prev => [b, ...prev]); setShowBoostModal(false); }}
          onClose={() => setShowBoostModal(false)}
        />
      )}
    </div>
  );
}

// ── Add Task Modal ────────────────────────────────────────────────────────────

interface ModalProps {
  accounts: Account[];
  onCreated: (task: BotTask) => void;
  onClose: () => void;
}

type Step = "account" | "chat" | "settings";

function AddTaskModal({ accounts, onCreated, onClose }: ModalProps) {
  const [step, setStep] = useState<Step>("account");
  const [accountId, setAccountId] = useState<number | null>(null);
  const [dialogs, setDialogs] = useState<Dialog[]>([]);
  const [loadingDialogs, setLoadingDialogs] = useState(false);
  const [selectedDialog, setSelectedDialog] = useState<Dialog | null>(null);

  const [persona, setPersona] = useState("Дружелюбный, открытый человек, интересуется технологиями и повседневной жизнью");
  const [replyProb, setReplyProb] = useState(70);
  const [minDelay, setMinDelay] = useState(5);
  const [maxDelay, setMaxDelay] = useState(30);
  const [proactiveInterval, setProactiveInterval] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSelectAccount(id: number) {
    setAccountId(id);
    setLoadingDialogs(true);
    try {
      const all = await api.getDialogs(id);
      setDialogs(all.filter((d) => d.is_group));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoadingDialogs(false);
    }
    setStep("chat");
  }

  async function handleSubmit() {
    if (!accountId || !selectedDialog) return;
    setSubmitting(true);
    setError("");
    try {
      const payload: CreateTaskPayload = {
        account_id: accountId,
        chat_id: selectedDialog.id,
        chat_name: selectedDialog.name,
        persona,
        reply_probability: replyProb,
        min_delay: minDelay,
        max_delay: maxDelay,
        proactive_interval: proactiveInterval ? parseInt(proactiveInterval, 10) : null,
      };
      const task = await api.createTask(payload);
      onCreated(task);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={s.overlay}>
      <div style={s.modal}>
        <div style={s.modalHeader}>
          <span style={s.modalTitle}>Новая задача</span>
          <div style={s.steps}>
            <StepDot n={1} label="Аккаунт" active={step === "account"} done={step !== "account"} />
            <div style={s.stepLine} />
            <StepDot n={2} label="Чат" active={step === "chat"} done={step === "settings"} />
            <div style={s.stepLine} />
            <StepDot n={3} label="Настройки" active={step === "settings"} done={false} />
          </div>
        </div>

        {step === "account" && (
          <div style={s.stepBody}>
            <div style={s.hint}>Выберите аккаунт, от которого будет работать бот:</div>
            {accounts.map((acc) => (
              <button key={acc.id} style={s.accountBtn} onClick={() => handleSelectAccount(acc.id)}>
                <span style={{ ...s.avatar, background: acc.avatar_color }}>
                  {(acc.first_name || acc.label)[0].toUpperCase()}
                </span>
                <div>
                  <div style={s.accName}>{acc.label}</div>
                  <div style={s.accPhone}>{acc.phone}</div>
                </div>
              </button>
            ))}
          </div>
        )}

        {step === "chat" && (
          <div style={s.stepBody}>
            <div style={s.hint}>Выберите группу/чат:</div>
            {loadingDialogs && <div style={s.loading}>Загрузка чатов...</div>}
            <div style={s.dialogScroll}>
              {dialogs.map((d) => (
                <button
                  key={d.id}
                  style={{ ...s.dialogBtn, ...(selectedDialog?.id === d.id ? s.dialogBtnActive : {}) }}
                  onClick={() => setSelectedDialog(d)}
                >
                  <div style={s.dName}>{d.name}</div>
                  {d.last_message && <div style={s.dPreview}>{d.last_message}</div>}
                </button>
              ))}
            </div>
            <button
              style={{ ...s.nextBtn, opacity: selectedDialog ? 1 : 0.4 }}
              disabled={!selectedDialog}
              onClick={() => setStep("settings")}
            >
              Далее →
            </button>
          </div>
        )}

        {step === "settings" && (
          <div style={s.stepBody}>
            <div style={s.hint}>Настройте поведение бота в <b style={{ color: "#fff" }}>{selectedDialog?.name}</b>:</div>

            <label style={s.label}>Персона (описание характера)</label>
            <textarea
              style={s.textarea}
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              rows={3}
            />

            <label style={s.label}>Вероятность ответа: <b style={{ color: "#60a5fa" }}>{replyProb}%</b></label>
            <input
              type="range" min={10} max={100} value={replyProb}
              onChange={(e) => setReplyProb(Number(e.target.value))}
              style={s.range}
            />

            <div style={s.row}>
              <div style={{ flex: 1 }}>
                <label style={s.label}>Мин. задержка (сек)</label>
                <input
                  type="number" style={s.input} value={minDelay} min={1}
                  onChange={(e) => setMinDelay(Number(e.target.value))}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label style={s.label}>Макс. задержка (сек)</label>
                <input
                  type="number" style={s.input} value={maxDelay} min={1}
                  onChange={(e) => setMaxDelay(Number(e.target.value))}
                />
              </div>
            </div>

            <label style={s.label}>Новая тема каждые N минут (необязательно)</label>
            <input
              type="number" style={s.input} value={proactiveInterval}
              placeholder="например: 30 (оставьте пустым, чтобы отключить)"
              onChange={(e) => setProactiveInterval(e.target.value)}
            />

            <button style={s.submitBtn} onClick={handleSubmit} disabled={submitting}>
              {submitting ? "Запускаем..." : "Запустить задачу"}
            </button>
          </div>
        )}

        {error && <div style={s.error}>{error}</div>}

        <button style={s.cancelBtn} onClick={onClose}>Отмена</button>
      </div>
    </div>
  );
}

function StepDot({ n, label, active, done }: { n: number; label: string; active: boolean; done: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
      <div style={{
        width: 28, height: 28, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 13, fontWeight: 700,
        background: active ? "#2b6be6" : done ? "#22c55e" : "#2a2a2a",
        color: "#fff",
        border: active ? "2px solid #2b6be6" : done ? "2px solid #22c55e" : "2px solid #3a3a3a",
      }}>
        {done ? "✓" : n}
      </div>
      <span style={{ fontSize: 10, color: active ? "#fff" : "#666" }}>{label}</span>
    </div>
  );
}

// ── Boost Panel ───────────────────────────────────────────────────────────────

const BOOST_STATUS_LABEL: Record<string, { label: string; color: string }> = {
  running: { label: "В процессе", color: "#a78bfa" },
  done:    { label: "Завершён",   color: "#22c55e" },
  cancelled: { label: "Отменён", color: "#6b7280" },
};

function BoostPanel({ boosts, onCancel }: { boosts: BoostTask[]; onCancel: (id: number) => void }) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [logs, setLogs] = useState<Record<number, BoostLog[]>>({});

  async function loadLogs(id: number) {
    try {
      const l = await api.getBoostLogs(id);
      setLogs(prev => ({ ...prev, [id]: l }));
    } catch {}
  }

  function toggleExpand(id: number) {
    if (expandedId === id) {
      setExpandedId(null);
    } else {
      setExpandedId(id);
      loadLogs(id);
    }
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
      {boosts.length === 0 && (
        <div style={s.empty}>Нажми «Запустить буст» чтобы разогнать обсуждение конкретного поста</div>
      )}
      {boosts.map(b => {
        const badge = BOOST_STATUS_LABEL[b.status] || BOOST_STATUS_LABEL.done;
        const progress = b.total_accounts > 0 ? Math.round((b.comments_posted / b.total_accounts) * 100) : 0;
        const created = new Date(b.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
        const ends = new Date(b.ends_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
        const isExpanded = expandedId === b.id;

        return (
          <div key={b.id} style={{ background: "#1a1a1a", borderRadius: 12, padding: 16, border: "1px solid #2a2a2a" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <span style={{ color: "#fff", fontWeight: 700, fontSize: 15 }}>Буст #{b.id}</span>
              <span style={{ fontSize: 11, fontWeight: 600, border: "1px solid", borderRadius: 20, padding: "2px 10px", color: badge.color, borderColor: badge.color }}>{badge.label}</span>
            </div>
            <div style={{ color: "#aaa", fontSize: 12, marginBottom: 4, wordBreak: "break-all" }}>
              Сообщение: <span style={{ color: "#60a5fa" }}>{b.message_link}</span>
            </div>
            {b.topic && (
              <div style={{ color: "#aaa", fontSize: 12, marginBottom: 4 }}>
                Тема: <span style={{ color: "#e2e8f0" }}>{b.topic}</span>
              </div>
            )}
            <div style={{ color: "#555", fontSize: 11, marginBottom: 10 }}>
              {created} → {ends} · {b.duration_minutes} мин
            </div>

            {/* Progress bar */}
            <div style={{ background: "#222", borderRadius: 4, height: 6, marginBottom: 6 }}>
              <div style={{ background: b.status === "done" ? "#22c55e" : "#a78bfa", borderRadius: 4, height: 6, width: `${progress}%`, transition: "width 0.5s" }} />
            </div>
            <div style={{ color: "#888", fontSize: 11, marginBottom: 10 }}>
              {b.comments_posted} из {b.total_accounts} аккаунтов прокомментировали
            </div>

            <div style={{ display: "flex", gap: 8 }}>
              <button style={{ background: "#1a1a2e", color: "#a78bfa", border: "1px solid #4c1d95", borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontSize: 12 }}
                onClick={() => toggleExpand(b.id)}>
                {isExpanded ? "Скрыть" : "Лог"}
              </button>
              {b.status === "running" && (
                <button style={s.btnStop} onClick={() => onCancel(b.id)}>⛔ Отменить</button>
              )}
            </div>

            {isExpanded && (
              <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
                {(logs[b.id] || []).length === 0 && <div style={{ color: "#555", fontSize: 12 }}>Логов пока нет</div>}
                {(logs[b.id] || []).map(log => (
                  <div key={log.id} style={{ fontSize: 12, display: "flex", gap: 8, alignItems: "baseline" }}>
                    <span style={{ color: "#555" }}>{new Date(log.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</span>
                    <span style={{ color: "#888" }}>{log.account_label || `#${log.account_id}`}</span>
                    <span style={{ color: log.action === "error" ? "#ef4444" : "#22c55e", fontWeight: 600 }}>{log.action === "commented" ? "✓" : "✗"}</span>
                    {log.text && <span style={{ color: "#ccc", fontStyle: "italic" }}>"{log.text}"</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Boost Modal ───────────────────────────────────────────────────────────────

function BoostModal({ onCreated, onClose }: { onCreated: (b: BoostTask) => void; onClose: () => void }) {
  const [messageLink, setMessageLink] = useState("");
  const [topic, setTopic] = useState("");
  const [duration, setDuration] = useState(60);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit() {
    if (!messageLink.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      const boost = await api.createBoost({
        message_link: messageLink.trim(),
        topic: topic.trim() || undefined,
        duration_minutes: duration,
      });
      onCreated(boost);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={s.overlay}>
      <div style={s.modal}>
        <span style={s.modalTitle}>🚀 Буст поста</span>
        <div style={{ color: "#aaa", fontSize: 13 }}>
          Все боты в течение указанного времени оставят комментарии под выбранным сообщением, имитируя живое обсуждение.
        </div>

        <label style={s.label}>Ссылка на сообщение или его ID</label>
        <input
          style={s.input}
          value={messageLink}
          onChange={e => setMessageLink(e.target.value)}
          placeholder="https://t.me/c/123456/42  или  42"
        />
        <div style={{ color: "#555", fontSize: 11 }}>
          В Telegram: правая кнопка на сообщении → Копировать ссылку. Или введи только ID сообщения.
        </div>

        <label style={s.label}>Тема обсуждения (необязательно)</label>
        <textarea
          style={s.textarea}
          value={topic}
          onChange={e => setTopic(e.target.value)}
          rows={2}
          placeholder="Оставь пустым — боты сами проанализируют пост и придумают тему"
        />

        <label style={s.label}>Длительность: <b style={{ color: "#a78bfa" }}>{duration} мин</b></label>
        <input
          type="range" min={15} max={180} step={5} value={duration}
          onChange={e => setDuration(+e.target.value)}
          style={{ ...s.range, accentColor: "#7c3aed" }}
        />
        <div style={{ color: "#555", fontSize: 11 }}>
          Комментарии будут равномерно распределены по всему времени
        </div>

        {error && <div style={s.error}>{error}</div>}

        <button
          style={{ ...s.submitBtn, background: "#7c3aed", opacity: messageLink.trim() ? 1 : 0.4 }}
          disabled={!messageLink.trim() || submitting}
          onClick={handleSubmit}
        >
          {submitting ? "Запускаем..." : "🚀 Запустить буст"}
        </button>
        <button style={s.cancelBtn} onClick={onClose}>Отмена</button>
      </div>
    </div>
  );
}

// ── Add Channel Task Modal ────────────────────────────────────────────────────

function AddChannelTaskModal({ accounts, onCreated, onClose }: { accounts: Account[]; onCreated: (t: ChannelTask) => void; onClose: () => void }) {
  const [accountId, setAccountId] = useState<number | null>(null);
  const [keywords, setKeywords] = useState("IT новости, технологии, искусственный интеллект");
  const [persona, setPersona] = useState("Любознательный IT-специалист, интересуется технологиями и следит за новинками");
  const [maxChannels, setMaxChannels] = useState(5);
  const [commentProb, setCommentProb] = useState(40);
  const [reactionProb, setReactionProb] = useState(60);
  const [checkInterval, setCheckInterval] = useState(60);
  const [maxDaily, setMaxDaily] = useState(15);
  const [sessionMode, setSessionMode] = useState<SessionMode>("always");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit() {
    if (!accountId) return;
    setSubmitting(true);
    setError("");
    try {
      const payload: CreateChannelTaskPayload = {
        account_id: accountId, keywords, persona,
        max_channels: maxChannels, comment_probability: commentProb,
        reaction_probability: reactionProb, check_interval: checkInterval,
        max_daily_actions: maxDaily, session_mode: sessionMode,
      };
      const task = await api.createChannelTask(payload);
      onCreated(task);
    } catch (e: any) { setError(e.message); }
    finally { setSubmitting(false); }
  }

  return (
    <div style={s.overlay}>
      <div style={s.modal}>
        <span style={s.modalTitle}>Мониторинг каналов</span>
        <div style={s.hint}>Выберите аккаунт:</div>
        {accounts.map(acc => (
          <button key={acc.id} style={{...s.accountBtn, ...(accountId === acc.id ? {borderColor: "#2b6be6", background: "#1e3a5f"} : {})}} onClick={() => setAccountId(acc.id)}>
            <span style={{...s.avatar, background: acc.avatar_color}}>{(acc.first_name || acc.label)[0].toUpperCase()}</span>
            <div><div style={s.accName}>{acc.label}</div><div style={s.accPhone}>{acc.phone}</div></div>
          </button>
        ))}
        <label style={s.label}>Ключевые слова (через запятую)</label>
        <input style={s.input} value={keywords} onChange={e => setKeywords(e.target.value)} placeholder="IT новости, технологии" />
        <label style={s.label}>Персона</label>
        <textarea style={s.textarea} value={persona} onChange={e => setPersona(e.target.value)} rows={2} />
        <div style={s.row}>
          <div style={{flex:1}}><label style={s.label}>Макс. каналов</label><input type="number" style={s.input} value={maxChannels} min={1} max={20} onChange={e => setMaxChannels(+e.target.value)} /></div>
          <div style={{flex:1}}><label style={s.label}>Макс. действий/день</label><input type="number" style={s.input} value={maxDaily} min={1} onChange={e => setMaxDaily(+e.target.value)} /></div>
        </div>
        <label style={s.label}>Вероятность реакции: <b style={{color:"#f59e0b"}}>{reactionProb}%</b></label>
        <input type="range" min={0} max={100} value={reactionProb} onChange={e => setReactionProb(+e.target.value)} style={s.range} />
        <label style={s.label}>Вероятность комментария: <b style={{color:"#60a5fa"}}>{commentProb}%</b></label>
        <input type="range" min={0} max={100} value={commentProb} onChange={e => setCommentProb(+e.target.value)} style={s.range} />
        <label style={s.label}>Проверять каждые {checkInterval} мин</label>
        <input type="range" min={15} max={360} step={15} value={checkInterval} onChange={e => setCheckInterval(+e.target.value)} style={s.range} />
        <label style={s.label}>Режим активности</label>
        <div style={{display:"flex", flexDirection:"column", gap:4}}>
          {(["always","random","work_hours","evening"] as SessionMode[]).map(mode => (
            <button key={mode} onClick={() => setSessionMode(mode)}
              style={{background: sessionMode===mode ? "#1e3a5f" : "#222", border: `1px solid ${sessionMode===mode ? "#2b6be6" : "#2a2a2a"}`, borderRadius:8, padding:"8px 12px", cursor:"pointer", textAlign:"left", color: sessionMode===mode ? "#fff" : "#888", fontSize:13}}>
              {sessionMode === mode && "✓ "}{SESSION_MODE_LABELS[mode]}
            </button>
          ))}
        </div>
        {error && <div style={s.error}>{error}</div>}
        <button style={{...s.submitBtn, opacity: accountId ? 1 : 0.4}} disabled={!accountId || submitting} onClick={handleSubmit}>
          {submitting ? "Запускаем..." : "Запустить мониторинг"}
        </button>
        <button style={s.cancelBtn} onClick={onClose}>Отмена</button>
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  root: { display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", background: "#121212" },
  header: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid #2a2a2a" },
  headerLeft: { display: "flex", alignItems: "center", gap: 16 },
  mainTabs: { display: "flex", background: "#1a1a1a", borderRadius: 8, padding: 3, gap: 2 },
  mainTab: { padding: "5px 14px", background: "none", border: "none", color: "#666", cursor: "pointer", fontSize: 12, fontWeight: 600, borderRadius: 6 },
  mainTabActive: { background: "#2a2a2a", color: "#fff" },
  title: { color: "#fff", fontWeight: 700, fontSize: 18 },
  addBtn: { background: "#2b6be6", color: "#fff", border: "none", borderRadius: 8, padding: "8px 16px", cursor: "pointer", fontWeight: 600, fontSize: 13 },
  body: { display: "flex", flex: 1, overflow: "hidden" },
  taskPanel: { width: 380, borderRight: "1px solid #2a2a2a", overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 12 },
  logPanel: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" },
  panelTitle: { color: "#aaa", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, marginBottom: 12 },
  empty: { color: "#555", fontSize: 13, textAlign: "center", padding: 24 },
  taskCard: { background: "#1a1a1a", borderRadius: 10, padding: 14, border: "1px solid #2a2a2a", display: "flex", flexDirection: "column", gap: 6 },
  taskRow: { display: "flex", alignItems: "center", justifyContent: "space-between" },
  taskAccount: { color: "#fff", fontWeight: 600, fontSize: 14 },
  taskBadge: { fontSize: 11, fontWeight: 600, border: "1px solid", borderRadius: 20, padding: "2px 10px" },
  taskChat: { color: "#aaa", fontSize: 13 },
  taskMeta: { color: "#555", fontSize: 11 },
  taskActions: { display: "flex", gap: 8, marginTop: 4 },
  btnPause: { background: "#1e3a5f", color: "#60a5fa", border: "1px solid #2b6be6", borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontSize: 12 },
  btnPlay: { background: "#14532d", color: "#22c55e", border: "1px solid #16a34a", borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontSize: 12 },
  btnStop: { background: "#2a1a1a", color: "#ef4444", border: "1px solid #7f1d1d", borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontSize: 12 },
  btnTrigger: { background: "#1a2a1a", color: "#4ade80", border: "1px solid #16a34a", borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontSize: 12, fontWeight: 600 },
  logList: { flex: 1, overflowY: "auto", padding: "12px 16px", display: "flex", flexDirection: "column", gap: 6 },
  logItem: { display: "flex", alignItems: "baseline", gap: 6, fontSize: 12, flexWrap: "wrap" },
  logError: { opacity: 0.7 },
  logTime: { color: "#555", flexShrink: 0 },
  logAccount: { color: "#888", flexShrink: 0 },
  logAction: { fontWeight: 600, flexShrink: 0 },
  logText: { color: "#ccc", fontStyle: "italic", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 500 },
  // Modal
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 },
  modal: { background: "#1a1a1a", borderRadius: 14, padding: 24, width: 480, maxHeight: "85vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 16, border: "1px solid #2a2a2a" },
  modalHeader: { display: "flex", flexDirection: "column", gap: 16 },
  modalTitle: { color: "#fff", fontWeight: 700, fontSize: 18 },
  steps: { display: "flex", alignItems: "center", gap: 0 },
  stepLine: { flex: 1, height: 1, background: "#2a2a2a", margin: "0 8px 16px" },
  stepBody: { display: "flex", flexDirection: "column", gap: 10, overflowY: "auto" },
  hint: { color: "#aaa", fontSize: 13 },
  loading: { color: "#666", fontSize: 13 },
  accountBtn: { display: "flex", alignItems: "center", gap: 12, background: "#222", border: "1px solid #2a2a2a", borderRadius: 10, padding: "10px 14px", cursor: "pointer", textAlign: "left" },
  avatar: { width: 36, height: 36, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 16, flexShrink: 0 },
  accName: { color: "#fff", fontWeight: 600, fontSize: 14 },
  accPhone: { color: "#666", fontSize: 12 },
  dialogScroll: { maxHeight: 300, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 },
  dialogBtn: { background: "none", border: "1px solid #2a2a2a", borderRadius: 8, padding: "8px 12px", cursor: "pointer", textAlign: "left" },
  dialogBtnActive: { background: "#1e3a5f", borderColor: "#2b6be6" },
  dName: { color: "#fff", fontSize: 13, fontWeight: 500 },
  dPreview: { color: "#666", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  nextBtn: { background: "#2b6be6", color: "#fff", border: "none", borderRadius: 8, padding: "10px 0", cursor: "pointer", fontWeight: 600 },
  label: { color: "#888", fontSize: 12 },
  textarea: { background: "#222", border: "1px solid #2a2a2a", color: "#fff", padding: "8px 10px", borderRadius: 8, fontSize: 13, outline: "none", resize: "vertical", fontFamily: "inherit" },
  range: { width: "100%", accentColor: "#2b6be6" },
  row: { display: "flex", gap: 12 },
  input: { background: "#222", border: "1px solid #2a2a2a", color: "#fff", padding: "8px 10px", borderRadius: 8, fontSize: 13, outline: "none", width: "100%" },
  submitBtn: { background: "#2b6be6", color: "#fff", border: "none", borderRadius: 8, padding: "12px 0", cursor: "pointer", fontWeight: 700, fontSize: 14, marginTop: 4 },
  cancelBtn: { background: "none", color: "#666", border: "none", cursor: "pointer", fontSize: 13, alignSelf: "center" },
  error: { color: "#ef4444", fontSize: 12 },
};
