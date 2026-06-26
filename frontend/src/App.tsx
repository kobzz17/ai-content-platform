import { useEffect, useState } from "react";
import { api, Account } from "./api/client";
import { AccountSidebar } from "./components/AccountSidebar";
import { ChatView } from "./components/ChatView";
import { AIPanel } from "./components/AIPanel";
import { AutomationView } from "./components/AutomationView";

type Tab = "chats" | "automation";

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
        </div>
        <AccountSidebar
          accounts={accounts}
          selectedId={selectedAccountId}
          onSelect={setSelectedAccountId}
          onAddAccount={() => setShowAddForm(true)}
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
      ) : (
        <AutomationView accounts={accounts} />
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
