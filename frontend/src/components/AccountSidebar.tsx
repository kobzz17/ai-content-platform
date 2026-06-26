import { Account } from "../api/client";

interface Props {
  accounts: Account[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onAddAccount: () => void;
}

export function AccountSidebar({ accounts, selectedId, onSelect, onAddAccount }: Props) {
  return (
    <aside style={styles.sidebar}>
      <div style={styles.header}>
        <span style={styles.title}>Аккаунты</span>
        <button style={styles.addBtn} onClick={onAddAccount} title="Добавить аккаунт">+</button>
      </div>

      <div style={styles.list}>
        {accounts.map((acc) => (
          <button
            key={acc.id}
            style={{
              ...styles.item,
              ...(selectedId === acc.id ? styles.itemActive : {}),
            }}
            onClick={() => onSelect(acc.id)}
          >
            <div
              style={{
                ...styles.avatar,
                background: acc.avatar_color,
              }}
            >
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
