import { useState, useEffect } from "react";
import { api, Proxy, Account } from "../api/client";

interface Props {
  accounts: Account[];
}

export default function ProxyView({ accounts }: Props) {
  const [proxies, setProxies] = useState<Proxy[]>([]);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState<number | null>(null);

  // Add single proxy
  const [showAdd, setShowAdd] = useState(false);
  const [addProtocol, setAddProtocol] = useState("socks5");
  const [addHost, setAddHost] = useState("");
  const [addPort, setAddPort] = useState("1080");
  const [addUser, setAddUser] = useState("");
  const [addPass, setAddPass] = useState("");
  const [addError, setAddError] = useState("");

  // Batch add
  const [showBatch, setShowBatch] = useState(false);
  const [batchText, setBatchText] = useState("");
  const [batchResult, setBatchResult] = useState<{ added: number; failed: object[] } | null>(null);

  // Assign proxy
  const [assignProxyId, setAssignProxyId] = useState<number | null>(null);
  const [assignAccountId, setAssignAccountId] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      setProxies(await api.listProxies());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const addProxy = async () => {
    setAddError("");
    if (!addHost || !addPort) { setAddError("Заполните хост и порт"); return; }
    try {
      await api.addProxy({
        protocol: addProtocol,
        host: addHost,
        port: Number(addPort),
        username: addUser || undefined,
        password: addPass || undefined,
      });
      setShowAdd(false);
      setAddHost(""); setAddPort("1080"); setAddUser(""); setAddPass("");
      load();
    } catch (e: unknown) {
      setAddError(e instanceof Error ? e.message : "Ошибка");
    }
  };

  const addBatch = async () => {
    const lines = batchText.split("\n").filter((l) => l.trim());
    const result = await api.addProxiesBatch(lines);
    setBatchResult(result);
    load();
  };

  const checkProxy = async (id: number) => {
    setChecking(id);
    try {
      await api.checkProxy(id);
      load();
    } finally {
      setChecking(null);
    }
  };

  const deleteProxy = async (id: number) => {
    if (!confirm("Удалить прокси?")) return;
    await api.deleteProxy(id);
    load();
  };

  const autoAssign = async () => {
    const r = await api.autoAssignProxies() as { assigned: number };
    alert(`Назначено ${r.assigned} прокси`);
    load();
  };

  const assignProxy = async () => {
    if (!assignProxyId || !assignAccountId) return;
    await api.assignProxy(assignProxyId, assignAccountId);
    setAssignProxyId(null);
    load();
  };

  const healthyCount = proxies.filter((p) => p.is_healthy).length;
  const assignedCount = proxies.filter((p) => p.assigned_account_id).length;

  return (
    <div style={{ padding: "20px", color: "#e2e8f0", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: "0 0 4px" }}>Прокси</h2>
          <div style={{ fontSize: 13, color: "#64748b" }}>
            {proxies.length} всего · {healthyCount} живых · {assignedCount} назначено
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={autoAssign}
            style={{ padding: "8px 14px", borderRadius: 6, border: "1px solid #334155", background: "transparent", color: "#94a3b8", cursor: "pointer", fontSize: 13 }}
          >Авто-назначить</button>
          <button
            onClick={() => setShowBatch(true)}
            style={{ padding: "8px 14px", borderRadius: 6, border: "1px solid #3b82f640", background: "transparent", color: "#60a5fa", cursor: "pointer", fontSize: 13 }}
          >Импорт списком</button>
          <button
            onClick={() => setShowAdd(true)}
            style={{ padding: "8px 14px", borderRadius: 6, border: "none", background: "#3b82f6", color: "#fff", cursor: "pointer", fontSize: 13 }}
          >+ Добавить</button>
        </div>
      </div>

      {loading && <div style={{ color: "#94a3b8" }}>Загрузка...</div>}

      {/* Proxy list */}
      {!loading && proxies.length === 0 && (
        <div style={{ color: "#64748b", textAlign: "center", marginTop: 60 }}>
          Нет прокси. Добавьте вручную или импортируйте список.
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 10 }}>
        {proxies.map((p) => (
          <div
            key={p.id}
            style={{
              background: "#1e293b", borderRadius: 8, padding: 14,
              border: `1px solid ${p.is_healthy ? "#334155" : "#ef444440"}`,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontFamily: "monospace", fontSize: 13 }}>
                  {p.protocol}://{p.host}:{p.port}
                </div>
                {p.username && (
                  <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>👤 {p.username}</div>
                )}
              </div>
              <div style={{
                width: 10, height: 10, borderRadius: "50%",
                background: p.is_healthy ? "#22c55e" : "#ef4444",
                marginTop: 3,
              }} />
            </div>

            {p.assigned_account_label && (
              <div style={{ fontSize: 12, color: "#60a5fa", marginTop: 6 }}>
                → {p.assigned_account_label}
              </div>
            )}

            {p.last_checked_at && (
              <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                Проверен: {new Date(p.last_checked_at).toLocaleString("ru")}
              </div>
            )}

            <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
              <button
                onClick={() => checkProxy(p.id)}
                disabled={checking === p.id}
                style={{ padding: "3px 10px", borderRadius: 4, border: "none", background: "#334155", color: "#e2e8f0", cursor: "pointer", fontSize: 12 }}
              >{checking === p.id ? "..." : "Проверить"}</button>
              <button
                onClick={() => { setAssignProxyId(p.id); setAssignAccountId(null); }}
                style={{ padding: "3px 10px", borderRadius: 4, border: "none", background: "#334155", color: "#e2e8f0", cursor: "pointer", fontSize: 12 }}
              >Назначить</button>
              <button
                onClick={() => deleteProxy(p.id)}
                style={{ padding: "3px 10px", borderRadius: 4, border: "none", background: "#ef444422", color: "#ef4444", cursor: "pointer", fontSize: 12 }}
              >✕</button>
            </div>

            {assignProxyId === p.id && (
              <div style={{ marginTop: 10, display: "flex", gap: 6 }}>
                <select
                  value={assignAccountId ?? ""}
                  onChange={(e) => setAssignAccountId(Number(e.target.value))}
                  style={{ flex: 1, background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 4, padding: "4px 6px", fontSize: 12 }}
                >
                  <option value="">— аккаунт —</option>
                  {accounts.filter((a) => a.is_active).map((a) => (
                    <option key={a.id} value={a.id}>{a.label}</option>
                  ))}
                </select>
                <button
                  onClick={assignProxy}
                  disabled={!assignAccountId}
                  style={{ padding: "4px 10px", borderRadius: 4, border: "none", background: "#3b82f6", color: "#fff", cursor: "pointer", fontSize: 12 }}
                >ОК</button>
                <button
                  onClick={() => setAssignProxyId(null)}
                  style={{ padding: "4px 10px", borderRadius: 4, border: "none", background: "#334155", color: "#e2e8f0", cursor: "pointer", fontSize: 12 }}
                >✕</button>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Add proxy modal */}
      {showAdd && (
        <div style={{ position: "fixed", inset: 0, background: "#00000099", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}>
          <div style={{ background: "#1e293b", borderRadius: 12, padding: 24, width: 360, border: "1px solid #334155" }}>
            <h3 style={{ margin: "0 0 16px" }}>Добавить прокси</h3>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 8, marginBottom: 12 }}>
              <div>
                <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 4 }}>Протокол</div>
                <select value={addProtocol} onChange={(e) => setAddProtocol(e.target.value)}
                  style={{ width: "100%", background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 6, padding: "7px 8px" }}>
                  <option>socks5</option>
                  <option>socks4</option>
                  <option>http</option>
                  <option>https</option>
                </select>
              </div>
              <div>
                <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 4 }}>Хост</div>
                <input value={addHost} onChange={(e) => setAddHost(e.target.value)} placeholder="192.168.1.1"
                  style={{ width: "100%", background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 6, padding: "7px 8px", boxSizing: "border-box" }} />
              </div>
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 4 }}>Порт</div>
              <input value={addPort} onChange={(e) => setAddPort(e.target.value)} placeholder="1080" type="number"
                style={{ width: "100%", background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 6, padding: "7px 8px", boxSizing: "border-box" }} />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 16 }}>
              <div>
                <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 4 }}>Логин</div>
                <input value={addUser} onChange={(e) => setAddUser(e.target.value)} placeholder="необязательно"
                  style={{ width: "100%", background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 6, padding: "7px 8px", boxSizing: "border-box" }} />
              </div>
              <div>
                <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 4 }}>Пароль</div>
                <input value={addPass} onChange={(e) => setAddPass(e.target.value)} placeholder="необязательно" type="password"
                  style={{ width: "100%", background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 6, padding: "7px 8px", boxSizing: "border-box" }} />
              </div>
            </div>

            {addError && <div style={{ color: "#ef4444", fontSize: 13, marginBottom: 12 }}>{addError}</div>}

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={() => setShowAdd(false)} style={{ padding: "8px 16px", borderRadius: 6, border: "1px solid #334155", background: "transparent", color: "#94a3b8", cursor: "pointer" }}>Отмена</button>
              <button onClick={addProxy} style={{ padding: "8px 16px", borderRadius: 6, border: "none", background: "#3b82f6", color: "#fff", cursor: "pointer" }}>Добавить</button>
            </div>
          </div>
        </div>
      )}

      {/* Batch import modal */}
      {showBatch && (
        <div style={{ position: "fixed", inset: 0, background: "#00000099", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}>
          <div style={{ background: "#1e293b", borderRadius: 12, padding: 24, width: 480, border: "1px solid #334155" }}>
            <h3 style={{ margin: "0 0 8px" }}>Импорт прокси списком</h3>
            <div style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
              По одному на строке: <code style={{ color: "#94a3b8" }}>socks5://user:pass@host:port</code> или <code style={{ color: "#94a3b8" }}>host:port</code>
            </div>
            <textarea
              value={batchText}
              onChange={(e) => setBatchText(e.target.value)}
              rows={10}
              placeholder={"socks5://user:pass@1.2.3.4:1080\n5.6.7.8:3128\n..."}
              style={{ width: "100%", background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 6, padding: "8px 10px", fontFamily: "monospace", fontSize: 12, resize: "vertical", boxSizing: "border-box" }}
            />
            {batchResult && (
              <div style={{ fontSize: 13, marginTop: 8, color: batchResult.failed.length ? "#f59e0b" : "#22c55e" }}>
                Добавлено: {batchResult.added}, ошибок: {batchResult.failed.length}
              </div>
            )}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
              <button onClick={() => { setShowBatch(false); setBatchText(""); setBatchResult(null); }}
                style={{ padding: "8px 16px", borderRadius: 6, border: "1px solid #334155", background: "transparent", color: "#94a3b8", cursor: "pointer" }}>
                Закрыть
              </button>
              <button onClick={addBatch} disabled={!batchText.trim()}
                style={{ padding: "8px 16px", borderRadius: 6, border: "none", background: "#3b82f6", color: "#fff", cursor: "pointer" }}>
                Импортировать
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
