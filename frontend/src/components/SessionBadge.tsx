import type { SessionStatus } from "../types";

interface Props {
  session: SessionStatus | null;
  onRefresh: () => void;
}

export function SessionBadge({ session, onRefresh }: Props) {
  const ok = session?.authenticated ?? false;
  return (
    <div className={`session-badge ${ok ? "ok" : "warn"}`}>
      <span className="dot" />
      <div className="session-text">
        <strong>{ok ? "Sessiya faol" : "Sessiya topilmadi"}</strong>
        <small>{session?.message ?? "Tekshirilmoqda..."}</small>
      </div>
      <button className="link-btn" onClick={onRefresh} title="Qayta tekshirish">
        Yangilash
      </button>
    </div>
  );
}
