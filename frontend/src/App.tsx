import { useEffect, useState } from "react";
import { api, Account } from "./api/client";
import { AccountSidebar } from "./components/AccountSidebar";
import { ChatView } from "./components/ChatView";
import { AIPanel } from "./components/AIPanel";
import { AutomationView } from "./components/AutomationView";
import WarmupView from "./components/WarmupView";
import ProxyView from "./components/ProxyView";

type Tab = "chats" | "automation" | "warmup" | "proxies";

export default function App() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [tab, setTab] = useState<Tab>("chats");

  // Add account form state
  const [phone, setPhone] = useState("");
  const [label, setLabel] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [authError, setAuthError] = useState("");
  const [showImport, setShowImport] = useState(false);
  const [importResult, setImportResult] = useState<{ ok: Account[]; failed: { label: string; error: string }[] } | null>(null);
  const [importing, setImporting] = useState(false);
  const [importMode, setImportMode] = useState<"session" | "tdata">("session");
  const [tdataPasscode, setTdataPasscode] = useState("");

  useEffect(() => {
    api.listAccounts().then(setAccounts);
  }, []);

  async function handleStartAuth() {
    setAuthError("");
    try {
      await api.startAuth(phone, label);
      setCodeSent(true);
    } catch (e: any) {
      setAuthError(e.message);
    }
  }

  async function handleConfirmAuth() {
    setAuthError("");
    try {
      const acc = await api.confirmAuth({ phone, code, label });
      setAccounts((prev) => [...prev, acc]);
      setShowAddForm(false);
      setPhone(""); setLabel(""); setCode(""); setCodeSent(false);
    } catch (e: any) {
      setAuthError(e.message);
    }
  }

  return (
    <div style={styles.root}>
      {/* Left sidebar */}
      <div style={styles.sidebar}>
        {/* Tab switcher */}
        <div style={styles.tabs}>
          <button
            style={{ ...styles.tab, ...(tab === "chats" ? styles.tabActive : {}) }}
            onClick={() => setTab("chats")}
          >
            💬 Чаты
          </button>
          <button
            style={{ ...styles.tab, ...(tab === "automation" ? styles.tabActive : {}) }}
            onClick={() => setTab("automation")}
          >
            🤖 Авто
          </button>
          <button
            style={{ ...styles.tab, ...(tab === "warmup" ? styles.tabActive : {}) }}
            onClick={() => setTab("warmup")}
          >
            🔥 Прогрев
          </button>
          <button
            style={{ ...styles.tab, ...(tab === "proxies" ? styles.tabActive : {}) }}
            onClick={() => setTab("proxies")}
          >
            🔒 Прокси
          </button>
        </div>
        <AccountSidebar
          accounts={accounts}
          selectedId={selectedAccountId}
          onSelect={setSelectedAccountId}
          onAddAccount={() => setShowAddForm(true)}
          onImport={() => { setShowImport(true); setImportResult(null); }}
          onDelete={async (id) => {
            await api.removeAccount(id);
            if (selectedAccountId === id) setSelectedAccountId(null);
            setAccounts((prev) => prev.filter((a) => a.id !== id));
          }}
        />
      </div>

      {/* Main content area */}
      {tab === "chats" ? (
        selectedAccountId ? (
          <>
            <ChatView accountId={selectedAccountId} />
            <AIPanel
              messages={[]}
              onUseSuggestion={(text) => navigator.clipboard.writeText(text)}
            />
          </>
        ) : (
          <div style={styles.empty}>Выбери аккаунт, чтобы начать</div>
        )
      ) : tab === "automation" ? (
        <AutomationView accounts={accounts} />
      ) : tab === "warmup" ? (
        <WarmupView accounts={accounts} />
      ) : (
        <ProxyView accounts={accounts} />
      )}

      {/* Batch import modal */}
      {showImport && (
        <div style={styles.overlay}>
          <div style={{...styles.modal, width: 480, maxHeight: "80vh", overflowY: "auto"}}>
            <h3 style={styles.modalTitle}>Импорт пакета аккаунтов</h3>
            {!importResult ? (
              <>
                {/* Mode selector */}
                <div style={{display:"flex", gap:6, marginBottom:4}}>
                  {(["session","tdata"] as const).map(m => (
                    <button key={m} onClick={() => setImportMode(m)} style={{
                      flex:1, padding:"7px 0", borderRadius:6, border:"1px solid",
                      cursor:"pointer", fontSize:12, fontWeight:600,
                      background: importMode===m ? "#2b6be6" : "none",
                      borderColor: importMode===m ? "#2b6be6" : "#444",
                      color: importMode===m ? "#fff" : "#888",
                    }}>
                      {m === "session" ? "Session strings" : "tdata (zip)"}
                    </button>
                  ))}
                </div>

                {importMode === "session" ? (
                  <>
                    <p style={styles.modalHint}>Загрузите JSON или текстовый файл со session strings:</p>
                    <p style={{...styles.modalHint, fontSize: 11, fontFamily: "monospace", background:"#1a1a1a", padding:"8px 10px", borderRadius:6, lineHeight:1.6}}>
                      JSON: {`[{"session":"1BQ...","label":"Акк 1"}]`}<br/>
                      TXT: 1BQ...{"\t"}Акк 1
                    </p>
                    <input type="file" accept=".json,.txt" style={{color:"#fff", fontSize:13}}
                      onChange={async (e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        setImporting(true);
                        try {
                          const res = await api.importBatch(f);
                          setImportResult(res);
                          if (res.ok.length > 0) setAccounts(prev => [...prev, ...res.ok]);
                        } catch (err: any) { alert(err.message); }
                        finally { setImporting(false); }
                      }}
                    />
                  </>
                ) : (
                  <>
                    <p style={styles.modalHint}>ZIP-архив с папками tdata от Telegram Desktop.</p>
                    <p style={{...styles.modalHint, fontSize:11, lineHeight:1.6}}>
                      Структура: в архиве одна или несколько папок с файлами key_data*.
                      Можно упаковать несколько tdata-папок (по одной на аккаунт).
                    </p>
                    <input
                      style={styles.modalInput}
                      placeholder="Пароль tdata (если есть — оставь пустым если нет)"
                      value={tdataPasscode}
                      onChange={e => setTdataPasscode(e.target.value)}
                    />
                    <input type="file" accept=".zip" style={{color:"#fff", fontSize:13}}
                      onChange={async (e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        setImporting(true);
                        try {
                          const res = await api.importTdata(f, tdataPasscode || undefined);
                          setImportResult(res);
                          if (res.ok.length > 0) setAccounts(prev => [...prev, ...res.ok]);
                        } catch (err: any) { alert(err.message); }
                        finally { setImporting(false); }
                      }}
                    />
                  </>
                )}
                {importing && <p style={{color:"#60a5fa", fontSize:13}}>Проверяем сессии...</p>}
              </>
            ) : (
              <>
                <div style={{color:"#22c55e", fontSize:14, fontWeight:600}}>✓ Успешно импортировано: {importResult.ok.length}</div>
                {importResult.ok.map((a, i) => (
                  <div key={i} style={{color:"#aaa", fontSize:13}}>• {a.label} ({a.phone})</div>
                ))}
                {importResult.failed.length > 0 && (
                  <>
                    <div style={{color:"#ef4444", fontSize:14, fontWeight:600, marginTop:8}}>✗ Ошибки: {importResult.failed.length}</div>
                    {importResult.failed.map((f, i) => (
                      <div key={i} style={{color:"#888", fontSize:12}}>• {f.label}: {f.error}</div>
                    ))}
                  </>
                )}
              </>
            )}
            <button style={styles.cancelBtn} onClick={() => { setShowImport(false); setImportResult(null); setTdataPasscode(""); }}>Закрыть</button>
          </div>
        </div>
      )}

      {/* Add account modal */}
      {showAddForm && (
        <div style={styles.overlay}>
          <div style={styles.modal}>
            <h3 style={styles.modalTitle}>Добавить аккаунт</h3>

            {!codeSent ? (
              <>
                <input style={styles.modalInput} placeholder="Название (например: Основной)" value={label} onChange={(e) => setLabel(e.target.value)} />
                <input style={styles.modalInput} placeholder="+79001234567" value={phone} onChange={(e) => setPhone(e.target.value)} />
                <button style={styles.modalBtn} onClick={handleStartAuth} disabled={!phone || !label}>
                  Отправить код
                </button>
              </>
            ) : (
              <>
                <p style={styles.modalHint}>Код отправлен на {phone}</p>
                <input style={styles.modalInput} placeholder="Код из Telegram" value={code} onChange={(e) => setCode(e.target.value)} />
                <button style={styles.modalBtn} onClick={handleConfirmAuth} disabled={!code}>
                  Подтвердить
                </button>
              </>
            )}

            {authError && <div style={styles.error}>{authError}</div>}
            <button style={styles.cancelBtn} onClick={() => { setShowAddForm(false); setCodeSent(false); setAuthError(""); }}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: { display: "flex", height: "100vh", background: "#121212", fontFamily: "system-ui, sans-serif", overflow: "hidden" },
  sidebar: { display: "flex", flexDirection: "column" },
  tabs: { display: "flex", borderBottom: "1px solid #2a2a2a" },
  tab: { flex: 1, padding: "10px 0", background: "none", border: "none", color: "#666", cursor: "pointer", fontSize: 12, fontWeight: 600 },
  tabActive: { color: "#fff", borderBottom: "2px solid #2b6be6" },
  empty: { flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#555", fontSize: 15 },
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 },
  modal: { background: "#1e1e1e", borderRadius: 12, padding: 24, width: 360, display: "flex", flexDirection: "column", gap: 10 },
  modalTitle: { color: "#fff", margin: 0, fontSize: 18 },
  modalHint: { color: "#aaa", margin: 0, fontSize: 13 },
  modalInput: { background: "#2a2a2a", border: "none", color: "#fff", padding: "10px 12px", borderRadius: 8, fontSize: 14, outline: "none" },
  modalBtn: { background: "#2b6be6", color: "#fff", border: "none", borderRadius: 8, padding: "10px 0", cursor: "pointer", fontSize: 14, fontWeight: 600 },
  cancelBtn: { background: "none", color: "#888", border: "none", cursor: "pointer", fontSize: 13 },
  error: { color: "#e05c5c", fontSize: 13 },
};
