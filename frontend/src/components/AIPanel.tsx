import { useState } from "react";
import { api, Message } from "../api/client";

interface Props {
  messages: Message[];
  onUseSuggestion: (text: string) => void;
}

export function AIPanel({ messages, onUseSuggestion }: Props) {
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [hint, setHint] = useState("");
  const [tone, setTone] = useState("friendly");
  const [loading, setLoading] = useState(false);
  const [improveText, setImproveText] = useState("");
  const [improveInstruction, setImproveInstruction] = useState("");
  const [improveResult, setImproveResult] = useState("");

  async function handleSuggest() {
    if (!messages.length) return;
    setLoading(true);
    setSuggestions([]);
    try {
      const conversation = messages.slice(-10).map((m) => ({ sender: m.sender, text: m.text }));
      const res = await api.suggest(conversation, hint, tone);
      setSuggestions(res.suggestions);
    } finally {
      setLoading(false);
    }
  }

  async function handleImprove() {
    if (!improveText.trim()) return;
    setLoading(true);
    try {
      const res = await api.improve(improveText, improveInstruction || "make it better");
      setImproveResult(res.result);
    } finally {
      setLoading(false);
    }
  }

  return (
    <aside style={styles.panel}>
      <div style={styles.header}>AI-ассистент</div>

      {/* Suggest replies */}
      <section style={styles.section}>
        <div style={styles.sectionTitle}>Варианты ответа</div>
        <select value={tone} onChange={(e) => setTone(e.target.value)} style={styles.select}>
          <option value="friendly">Дружелюбный</option>
          <option value="formal">Формальный</option>
          <option value="enthusiastic">Энтузиазм</option>
          <option value="brief">Кратко</option>
        </select>
        <input
          style={styles.input}
          placeholder="Цель ответа (необязательно)"
          value={hint}
          onChange={(e) => setHint(e.target.value)}
        />
        <button style={styles.btn} onClick={handleSuggest} disabled={loading || !messages.length}>
          {loading ? "Генерирую..." : "Предложить варианты"}
        </button>

        {suggestions.map((s, i) => (
          <div key={i} style={styles.suggestion}>
            <div style={styles.suggestionText}>{s}</div>
            <button style={styles.useBtn} onClick={() => onUseSuggestion(s)}>
              Использовать
            </button>
          </div>
        ))}
      </section>

      {/* Improve text */}
      <section style={styles.section}>
        <div style={styles.sectionTitle}>Улучшить текст</div>
        <textarea
          style={styles.textarea}
          placeholder="Вставь текст сюда..."
          value={improveText}
          onChange={(e) => setImproveText(e.target.value)}
          rows={3}
        />
        <input
          style={styles.input}
          placeholder="Инструкция: сделать короче, формальнее..."
          value={improveInstruction}
          onChange={(e) => setImproveInstruction(e.target.value)}
        />
        <button style={styles.btn} onClick={handleImprove} disabled={loading || !improveText.trim()}>
          {loading ? "..." : "Улучшить"}
        </button>
        {improveResult && (
          <div style={styles.suggestion}>
            <div style={styles.suggestionText}>{improveResult}</div>
            <button style={styles.useBtn} onClick={() => onUseSuggestion(improveResult)}>
              Использовать
            </button>
          </div>
        )}
      </section>
    </aside>
  );
}

const styles: Record<string, React.CSSProperties> = {
  panel: { width: 280, borderLeft: "1px solid #2a2a2a", display: "flex", flexDirection: "column", background: "#1a1a1a", overflowY: "auto" },
  header: { padding: "14px 12px", color: "#aaa", fontSize: 12, fontWeight: 600, textTransform: "uppercase", borderBottom: "1px solid #2a2a2a" },
  section: { padding: 12, borderBottom: "1px solid #1e1e1e" },
  sectionTitle: { color: "#fff", fontSize: 13, fontWeight: 600, marginBottom: 8 },
  select: { width: "100%", background: "#2a2a2a", border: "none", color: "#fff", padding: "6px 8px", borderRadius: 6, marginBottom: 6, fontSize: 13 },
  input: { width: "100%", background: "#2a2a2a", border: "none", color: "#fff", padding: "6px 8px", borderRadius: 6, marginBottom: 6, fontSize: 13, boxSizing: "border-box" },
  textarea: { width: "100%", background: "#2a2a2a", border: "none", color: "#fff", padding: "6px 8px", borderRadius: 6, marginBottom: 6, fontSize: 13, resize: "vertical", boxSizing: "border-box" },
  btn: { width: "100%", background: "#2b6be6", color: "#fff", border: "none", borderRadius: 6, padding: "7px 0", cursor: "pointer", fontSize: 13, marginBottom: 8 },
  suggestion: { background: "#2a2a2a", borderRadius: 8, padding: 10, marginBottom: 6 },
  suggestionText: { color: "#ddd", fontSize: 13, lineHeight: 1.5, marginBottom: 6 },
  useBtn: { background: "none", border: "1px solid #2b6be6", color: "#2b6be6", borderRadius: 4, padding: "3px 8px", cursor: "pointer", fontSize: 12 },
};
