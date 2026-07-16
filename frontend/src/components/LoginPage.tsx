import { useState } from "react";
import { setStoredApiKey, api } from "../api/client";

export function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    setStoredApiKey(key.trim());
    try {
      await api.listAccounts();
      onLogin();
    } catch (e: any) {
      setError("Неверный ключ доступа");
      setStoredApiKey("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      height: "100vh", background: "#0f0f0f",
    }}>
      <form onSubmit={handleSubmit} style={{
        background: "#1a1a1a", borderRadius: 12, padding: "40px 48px",
        display: "flex", flexDirection: "column", gap: 16, minWidth: 320,
        border: "1px solid #2a2a2a",
      }}>
        <div style={{ fontSize: 22, fontWeight: 600, color: "#fff", marginBottom: 8 }}>
          TG Manager
        </div>
        <input
          type="password"
          placeholder="Ключ доступа"
          value={key}
          onChange={e => setKey(e.target.value)}
          autoFocus
          style={{
            padding: "10px 14px", borderRadius: 8, border: "1px solid #333",
            background: "#111", color: "#fff", fontSize: 15, outline: "none",
          }}
        />
        {error && (
          <div style={{ color: "#f87171", fontSize: 13 }}>{error}</div>
        )}
        <button
          type="submit"
          disabled={loading || !key.trim()}
          style={{
            padding: "10px 0", borderRadius: 8, border: "none",
            background: loading || !key.trim() ? "#333" : "#3b82f6",
            color: "#fff", fontSize: 15, cursor: loading || !key.trim() ? "default" : "pointer",
            fontWeight: 500,
          }}
        >
          {loading ? "Проверка..." : "Войти"}
        </button>
      </form>
    </div>
  );
}
