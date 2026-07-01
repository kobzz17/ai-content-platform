import { useState, useRef } from "react";
import { Account } from "../api/client";

interface Props {
  accounts: Account[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onAddAccount: () => void;
  onImport?: () => void;
  onDelete?: (id: number) => void;
  onRename?: (id: number, newLabel: string) => void;
}

export function AccountSidebar({ accounts, selectedId, onSelect, onAddAccount, onImport, onDelete, onRename }: Props) {
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDelete = (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    if (confirmId === id) {
      onDelete?.(id);
      setConfirmId(null);
    } else {
      setConfirmId(id);
    }
  };

  const startEdit = (e: React.MouseEvent, acc: Account) => {
    e.stopPropagation();
    setEditingId(acc.id);
    setEditValue(acc.label);
    setConfirmId(null);
    setTimeout(() => inputRef.current?.select(), 30);
  };

  const commitEdit = () => {
    if (editingId !== null && editValue.trim()) {
      onRename?.(editingId, editValue.trim());
    }
    setEditingId(null);
  };

  const cancelEdit = () => setEditingId(null);

  return (
    <aside style={styles.sidebar}>
      <div style={styles.header}>
        <span style={styles.title}>Аккаунты</span>
        <div style={{display:"flex", gap:4}}>
          {onImport && (
            <button style={{...styles.addBtn, background:"#374151", fontSize:14}} onClick={onImport} title="Импорт пакета">↑</button>
          )}
          <button style={styles.addBtn} onClick={onAddAccount} title="Добавить аккаунт">+</button>
        </div>
      </div>

      <div style={styles.list}>
        {accounts.map((acc) => (
          <div
            key={acc.id}
            style={{ position: "relative" }}
            onMouseEnter={() => setHoveredId(acc.id)}
            onMouseLeave={() => { setHoveredId(null); setConfirmId(null); }}
          >
            {editingId === acc.id ? (
              <div style={{ padding: "8px 12px", display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ ...styles.avatar, background: acc.avatar_color }}>
                  {(acc.first_name || acc.phone)[0].toUpperCase()}
                </div>
                <input
                  ref={inputRef}
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") commitEdit(); if (e.key === "Escape") cancelEdit(); }}
                  onBlur={commitEdit}
                  style={{
                    flex: 1, background: "#2a2a2a", border: "1px solid #4a4a4a",
                    borderRadius: 4, color: "#fff", fontSize: 13, padding: "3px 6px",
                    outline: "none",
                  }}
                  autoFocus
                />
              </div>
            ) : (
              <button
                style={{
                  ...styles.item,
                  ...(selectedId === acc.id ? styles.itemActive : {}),
                }}
                onClick={() => onSelect(acc.id)}
              >
                <div style={{ ...styles.avatar, background: acc.avatar_color }}>
                  {(acc.first_name || acc.phone)[0].toUpperCase()}
                </div>
                <div style={styles.itemInfo}>
                  <div style={styles.itemName}>{acc.label}</div>
                  <div style={styles.itemPhone}>{acc.phone}</div>
                </div>
                {acc.unread_count > 0 && (
                  <span style={styles.badge}>{acc.unread_count}</span>
                )}
                {acc.status !== "active" && (
                  <span style={styles.statusDot} title={acc.status} />
                )}
              </button>
            )}

            {editingId !== acc.id && onDelete && hoveredId === acc.id && (
              <div style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", display: "flex", gap: 3 }}>
                {onRename && (
                  <button
                    onClick={(e) => startEdit(e, acc)}
                    title="Переименовать"
                    style={{ ...styles.iconBtn, background: "#374151" }}
                  >
                    ✎
                  </button>
                )}
                <button
                  onClick={(e) => handleDelete(e, acc.id)}
                  title={confirmId === acc.id ? "Нажми ещё раз для подтверждения" : "Удалить аккаунт"}
                  style={{ ...styles.iconBtn, background: confirmId === acc.id ? "#ef4444" : "#374151" }}
                >
                  {confirmId === acc.id ? "!" : "×"}
                </button>
              </div>
            )}
          </div>
        ))}

        {accounts.length === 0 && (
          <div style={styles.empty}>
            Нет аккаунтов.<br />Нажми + чтобы добавить.
          </div>
        )}
      </div>
    </aside>
  );
}

const styles: Record<string, React.CSSProperties> = {
  sidebar: {
    width: 240,
    borderRight: "1px solid #2a2a2a",
    display: "flex",
    flexDirection: "column",
    background: "#1a1a1a",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "16px 12px",
    borderBottom: "1px solid #2a2a2a",
  },
  title: { color: "#fff", fontWeight: 600, fontSize: 14 },
  addBtn: {
    background: "#2b6be6",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    width: 28,
    height: 28,
    fontSize: 20,
    cursor: "pointer",
    lineHeight: 1,
  },
  iconBtn: {
    color: "#fff",
    border: "none",
    borderRadius: 4,
    width: 20,
    height: 20,
    fontSize: 12,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    lineHeight: 1,
  },
  list: { overflowY: "auto", flex: 1 },
  item: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    width: "100%",
    padding: "10px 12px",
    background: "none",
    border: "none",
    cursor: "pointer",
    textAlign: "left",
  },
  itemActive: { background: "#2a2a2a" },
  avatar: {
    width: 38,
    height: 38,
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#fff",
    fontWeight: 700,
    fontSize: 16,
    flexShrink: 0,
  },
  itemInfo: { flex: 1, overflow: "hidden" },
  itemName: { color: "#fff", fontSize: 13, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" },
  itemPhone: { color: "#888", fontSize: 11 },
  badge: {
    background: "#2b6be6",
    color: "#fff",
    borderRadius: 10,
    padding: "1px 6px",
    fontSize: 11,
    fontWeight: 600,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    background: "#f5a623",
  },
  empty: { color: "#666", fontSize: 13, padding: 16, lineHeight: 1.6 },
};
