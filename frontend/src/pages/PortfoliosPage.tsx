import { useEffect, useState } from "react";
import { api, type PortfolioDetail, type PortfolioSummary } from "../api";

export function PortfoliosPage({
  portfolios,
  onClose,
  onRefresh,
  onOpenPhoto,
}: {
  portfolios: PortfolioSummary[];
  onClose: () => void;
  onRefresh: () => void;
  onOpenPhoto: (id: number) => void;
}) {
  const [openId, setOpenId] = useState<number | null>(null);

  return (
    <div className="modal-bg" onClick={onClose}>
      <div
        className="modal"
        style={{
          maxWidth: 880,
          flexDirection: "column",
          padding: 20,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ margin: "0 0 12px 0", fontSize: 18 }}>포트폴리오</h2>

        {portfolios.length === 0 ? (
          <div style={{ color: "var(--text-dim)", padding: 20 }}>
            아직 포트폴리오가 없습니다. 라이브러리에서 사진을 선택하고 "포트폴리오에 추가"를 눌러
            새로 만들어 주세요.
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
              gap: 12,
            }}
          >
            {portfolios.map((p) => (
              <div
                key={p.id}
                onClick={() => setOpenId(p.id)}
                style={{
                  background: "var(--panel-2)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: 10,
                  cursor: "pointer",
                }}
              >
                {p.preview_photo_id !== null ? (
                  <img
                    src={`/api/photos/${p.preview_photo_id}/thumb?size=400`}
                    alt={p.name}
                    style={{
                      width: "100%",
                      aspectRatio: "4/3",
                      objectFit: "cover",
                      borderRadius: 4,
                      marginBottom: 8,
                      background: "#000",
                    }}
                  />
                ) : (
                  <div
                    style={{
                      width: "100%",
                      aspectRatio: "4/3",
                      background: "#222",
                      borderRadius: 4,
                      marginBottom: 8,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "var(--text-dim)",
                      fontSize: 12,
                    }}
                  >
                    빈 포트폴리오
                  </div>
                )}
                <div style={{ fontWeight: 600, fontSize: 13 }}>{p.name}</div>
                <div style={{ color: "var(--text-dim)", fontSize: 11 }}>
                  {p.count}장
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
          <button className="ghost" onClick={onClose}>
            닫기
          </button>
        </div>
      </div>

      {openId !== null && (
        <PortfolioDetailModal
          portfolioId={openId}
          onClose={() => {
            setOpenId(null);
            onRefresh();
          }}
          onOpenPhoto={onOpenPhoto}
        />
      )}
    </div>
  );
}

function PortfolioDetailModal({
  portfolioId,
  onClose,
  onOpenPhoto,
}: {
  portfolioId: number;
  onClose: () => void;
  onOpenPhoto: (id: number) => void;
}) {
  const [detail, setDetail] = useState<PortfolioDetail | null>(null);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () =>
    api.portfolios.detail(portfolioId).then((d) => {
      setDetail(d);
      setEditName(d.name);
      setEditDesc(d.description ?? "");
    });

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portfolioId]);

  const remove = async (photoId: number) => {
    if (!detail) return;
    setBusy(true);
    try {
      await api.portfolios.removeItems(detail.id, [photoId]);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const saveMeta = async () => {
    if (!detail) return;
    setBusy(true);
    try {
      await api.portfolios.update(detail.id, {
        name: editName,
        description: editDesc,
      });
      setEditing(false);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const removeAll = async () => {
    if (!detail) return;
    if (!window.confirm(`"${detail.name}" 포트폴리오를 삭제할까요? 사진 자체는 유지됩니다.`))
      return;
    setBusy(true);
    try {
      await api.portfolios.remove(detail.id);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  if (!detail) {
    return (
      <div className="modal-bg" onClick={onClose}>
        <div className="empty">로딩 중...</div>
      </div>
    );
  }

  return (
    <div className="modal-bg" onClick={onClose} style={{ zIndex: 200 }}>
      <div
        className="modal"
        style={{
          maxWidth: 1000,
          flexDirection: "column",
          padding: 20,
          maxHeight: "92vh",
          overflowY: "auto",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
          <div style={{ flex: 1 }}>
            {editing ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  style={{ fontSize: 16, fontWeight: 600 }}
                />
                <textarea
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  rows={2}
                  placeholder="설명 (선택)"
                />
              </div>
            ) : (
              <>
                <h2 style={{ margin: 0, fontSize: 18 }}>{detail.name}</h2>
                {detail.description && (
                  <p style={{ color: "var(--text-dim)", fontSize: 12, margin: "4px 0 0 0" }}>
                    {detail.description}
                  </p>
                )}
              </>
            )}
            <div style={{ color: "var(--text-dim)", fontSize: 11, marginTop: 6 }}>
              {detail.items.length}장
            </div>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {editing ? (
              <>
                <button onClick={saveMeta} disabled={busy}>저장</button>
                <button className="ghost" onClick={() => setEditing(false)}>취소</button>
              </>
            ) : (
              <>
                <button className="ghost" onClick={() => setEditing(true)}>편집</button>
                <button className="ghost" onClick={removeAll} style={{ color: "var(--danger)" }}>
                  포트폴리오 삭제
                </button>
              </>
            )}
          </div>
        </div>

        {detail.items.length === 0 ? (
          <div style={{ color: "var(--text-dim)", padding: 20, textAlign: "center" }}>
            비어 있습니다.
          </div>
        ) : (
          <div
            style={{
              marginTop: 14,
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
              gap: 8,
            }}
          >
            {detail.items.map((it) => (
              <div key={it.photo_id} style={{ position: "relative" }}>
                <img
                  src={it.thumb_url}
                  alt={`#${it.photo_id}`}
                  onClick={() => {
                    onClose();
                    onOpenPhoto(it.photo_id);
                  }}
                  style={{
                    width: "100%",
                    aspectRatio: "4/3",
                    objectFit: "cover",
                    borderRadius: 4,
                    background: "#000",
                    cursor: "pointer",
                  }}
                />
                <button
                  className="ghost"
                  onClick={() => remove(it.photo_id)}
                  disabled={busy}
                  style={{
                    position: "absolute",
                    top: 4,
                    right: 4,
                    padding: "2px 8px",
                    fontSize: 11,
                    background: "rgba(0,0,0,0.7)",
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
          <button className="ghost" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}
