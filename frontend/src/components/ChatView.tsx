import { useEffect, useRef, useState } from "react";
import { api, Dialog, Message } from "../api/client";

interface Props {
  accountId: number;
}

export function ChatView({ accountId }: Props) {
  const [dialogs, setDialogs] = useState<Dialog[]>([]);
  const [selectedChat, setSelectedChat] = useState<Dialog | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingDialogs, setLoadingDialogs] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDialogs([]);
    setSelectedChat(null);
    setMessages([]);
    setLoadingDialogs(true);
    api.getDialogs(accountId)
      .then(setDialogs)
      .finally(() => setLoadingDialogs(false));
  }, [accountId]);

  useEffect(() => {
    if (!selectedChat) return;
    setLoadingMessages(true);
    api.getMessages(accountId, selectedChat.id)
      .then(setMessages)
      .finally(() => setLoadingMessages(false));
  }, [accountId, selectedChat]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend() {
    if (!text.trim() || !selectedChat) return;
    setSending(true);
    try {
      await api.sendMessage(accountId, selectedChat.id, text.trim());
      setMessages((prev) => [
        ...prev,
        { id: Date.now(), sender: "You", text: text.trim(), date: new Date().toISOString(), is_outgoing: true },
      ]);
      setText("");
    } finally {
      setSending(false);
    }
  }

  return (
    <div style={styles.root}>
      {/* Dialog list */}
      <div style={styles.dialogList}>
        <div style={styles.panelHeader}>Диалоги</div>
        {loadingDialogs && <div style={styles.loading}>Загрузка...</div>}
        {dialogs.map((d) => (
          <button
            key={d.id}
            style={{ ...styles.dialogItem, ...(selectedChat?.id === d.id ? styles.dialogActive : {}) }}
            onClick={() => setSelectedChat(d)}
          >
            <div style={styles.dialogName}>{d.name}</div>
            {d.last_message && <div style={styles.dialogPreview}>{d.last_message}</div>}
            {d.unread_count > 0 && <span style={styles.badge}>{d.unread_count}</span>}
          </button>
        ))}
      </div>

      {/* Message area */}
      <div style={styles.messageArea}>
        {selectedChat ? (
          <>
            <div style={styles.chatHeader}>{selectedChat.name}</div>
            <div style={styles.messages}>
              {loadingMessages && <div style={styles.loading}>Загрузка...</div>}
              {messages.map((m) => (
                <div
                  key={m.id}
                  style={{ ...styles.bubble, ...(m.is_outgoing ? styles.bubbleOut : styles.bubbleIn) }}
                >
                  {!m.is_outgoing && <div style={styles.bubbleSender}>{m.sender}</div>}
                  <div>{m.text}</div>
                  <div style={styles.bubbleTime}>
                    {new Date(m.date).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}
                  </div>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>

            <div style={styles.composer}>
              <textarea
                style={styles.textarea}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Сообщение..."
                rows={2}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
                }}
              />
              <button style={styles.sendBtn} onClick={handleSend} disabled={sending || !text.trim()}>
                {sending ? "..." : "→"}
              </button>
            </div>
          </>
        ) : (
          <div style={styles.placeholder}>Выбери диалог слева</div>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: { display: "flex", flex: 1, overflow: "hidden" },
  dialogList: { width: 260, borderRight: "1px solid #2a2a2a", display: "flex", flexDirection: "column", overflowY: "auto" },
  panelHeader: { padding: "14px 12px", color: "#aaa", fontSize: 12, fontWeight: 600, textTransform: "uppercase", borderBottom: "1px solid #2a2a2a" },
  dialogItem: { display: "block", width: "100%", padding: "10px 12px", background: "none", border: "none", cursor: "pointer", textAlign: "left", borderBottom: "1px solid #1e1e1e" },
  dialogActive: { background: "#2a2a2a" },
  dialogName: { color: "#fff", fontSize: 13, fontWeight: 500 },
  dialogPreview: { color: "#666", fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", marginTop: 2 },
  badge: { background: "#2b6be6", color: "#fff", borderRadius: 10, padding: "1px 6px", fontSize: 11, fontWeight: 600, float: "right" },
  messageArea: { flex: 1, display: "flex", flexDirection: "column" },
  chatHeader: { padding: "12px 16px", borderBottom: "1px solid #2a2a2a", color: "#fff", fontWeight: 600 },
  messages: { flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 8 },
  loading: { color: "#666", fontSize: 13, padding: 8 },
  bubble: { maxWidth: "72%", padding: "8px 12px", borderRadius: 12, fontSize: 14 },
  bubbleIn: { background: "#2a2a2a", color: "#fff", alignSelf: "flex-start" },
  bubbleOut: { background: "#2b6be6", color: "#fff", alignSelf: "flex-end" },
  bubbleSender: { fontSize: 11, color: "#aaa", marginBottom: 2 },
  bubbleTime: { fontSize: 10, color: "rgba(255,255,255,0.5)", textAlign: "right", marginTop: 4 },
  composer: { display: "flex", gap: 8, padding: 12, borderTop: "1px solid #2a2a2a" },
  textarea: { flex: 1, background: "#2a2a2a", border: "none", borderRadius: 8, color: "#fff", padding: "8px 12px", fontSize: 14, resize: "none", outline: "none" },
  sendBtn: { background: "#2b6be6", color: "#fff", border: "none", borderRadius: 8, padding: "0 16px", cursor: "pointer", fontSize: 18 },
  placeholder: { flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#555", fontSize: 14 },
};
