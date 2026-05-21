// 우하단 토스트 알림 스택. 주기 스캔/평가 완료를 사용자에게 비침습적으로 알림.

export interface ToastItem {
  id: number;
  text: string;
  kind: "scan" | "eval";
}

export function ToastStack({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`toast toast-${t.kind}`}
          onClick={() => onDismiss(t.id)}
          title="클릭해서 닫기"
        >
          <span className="toast-text">{t.text}</span>
          <button
            className="toast-close"
            onClick={(e) => {
              e.stopPropagation();
              onDismiss(t.id);
            }}
            aria-label="알림 닫기"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
