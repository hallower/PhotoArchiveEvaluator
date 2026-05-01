import { useEffect, useState } from "react";
import { api, type PhotoDetail } from "../api";

export function PhotoModal({
  photoId,
  onClose,
}: {
  photoId: number;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<PhotoDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [similar, setSimilar] = useState<
    { id: number; hamming: number; thumb_url: string }[] | null
  >(null);
  const [selectedPaths, setSelectedPaths] = useState<Set<number>>(new Set());

  const togglePath = (id: number) =>
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const load = () =>
    api.photos.detail(photoId).then(setDetail).catch(() => setDetail(null));

  useEffect(() => {
    void load();
    setSimilar(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photoId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const setUserScore = async (score: number | null) => {
    setBusy(true);
    try {
      if (score === null) {
        await api.photos.clearUserScore(photoId);
      } else {
        await api.photos.setUserScore(photoId, score);
      }
      await load();
    } finally {
      setBusy(false);
    }
  };

  const deleteSelectedPaths = async () => {
    if (!detail || selectedPaths.size === 0) return;
    const localCount = detail.paths.filter(
      (p) => p.nas_id === "local" && selectedPaths.has(p.id),
    ).length;
    let alsoFiles = false;
    if (localCount > 0) {
      alsoFiles = window.confirm(
        `${selectedPaths.size}개 경로를 라이브러리에서 제거합니다.\n` +
          `로컬 경로 ${localCount}개의 디스크 원본 파일도 삭제할까요?\n` +
          "확인 = 로컬 원본 삭제 / 취소 = DB 레코드만 삭제",
      );
    } else if (
      !window.confirm(`${selectedPaths.size}개 경로를 라이브러리에서 제거합니다.`)
    ) {
      return;
    }
    setBusy(true);
    try {
      const r = await api.photos.deletePaths(detail.id, [...selectedPaths], alsoFiles);
      setSelectedPaths(new Set());
      if (r.remaining_paths === 0) {
        alert("모든 경로 제거됨 — 사진은 missing 상태가 되었습니다.");
        onClose();
      } else {
        await load();
      }
    } finally {
      setBusy(false);
    }
  };

  const deletePhoto = async () => {
    if (!detail) return;
    if (
      !window.confirm(
        "이 사진을 라이브러리에서 완전히 삭제할까요?\n" +
          "(DB 레코드, 평가, 임베딩, 썸네일 캐시 모두 삭제. 디스크 원본은 보존)",
      )
    )
      return;
    const alsoFiles = window.confirm(
      "추가로 로컬 디스크의 원본 파일도 삭제할까요?\n" +
        "확인 = 로컬 원본 삭제 / 취소 = DB만 삭제",
    );
    setBusy(true);
    try {
      await api.photos.bulkDelete([detail.id], alsoFiles);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const findSimilar = async () => {
    setBusy(true);
    try {
      const r = await api.photos.similar(photoId, 12);
      setSimilar(
        r.items.map((it) => ({
          id: it.id,
          hamming: it.hamming,
          thumb_url: it.thumb_url,
        })),
      );
    } finally {
      setBusy(false);
    }
  };

  const aest = detail?.evaluations.find((e) => e.model_id !== "clip-prompt");
  const promptEval = detail?.evaluations.find((e) => e.model_id === "clip-prompt");
  const userScore = detail?.user_score ?? null;

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="photo-pane">
          {detail ? (
            <img src={`/api/photos/${detail.id}/thumb?size=800`} alt={`photo ${detail.id}`} />
          ) : (
            <div className="empty">불러오는 중...</div>
          )}
        </div>
        <div className="info-pane">
          {detail && (
            <>
              <h3>사진 정보</h3>
              <dl>
                <dt>미학 점수</dt>
                <dd>
                  {aest?.ai_score?.toFixed(2) ?? "-"} (raw{" "}
                  {aest?.raw_score?.toFixed(2) ?? "-"})
                </dd>
                <dt>prompt 점수</dt>
                <dd>
                  {promptEval?.ai_score?.toFixed(2) ?? "-"} (sim{" "}
                  {promptEval?.raw_score?.toFixed(3) ?? "-"})
                </dd>
                <dt>사용자 점수</dt>
                <dd>
                  <UserScoreEditor
                    current={userScore}
                    onSet={setUserScore}
                    disabled={busy}
                  />
                </dd>
                <dt>촬영일</dt>
                <dd>{detail.taken_at ?? "-"}</dd>
                <dt>카메라</dt>
                <dd>
                  {detail.camera_make} {detail.camera_model}
                </dd>
                <dt>렌즈</dt>
                <dd>{detail.lens_model ?? "-"}</dd>
                <dt>노출</dt>
                <dd>
                  ISO {detail.iso ?? "-"} / f/{detail.aperture ?? "-"} /{" "}
                  {detail.shutter ?? "-"} / {detail.focal_mm ?? "-"}mm
                </dd>
                <dt>크기</dt>
                <dd>
                  {detail.width}×{detail.height} ·{" "}
                  {detail.size_bytes ? Math.round(detail.size_bytes / 1024) : "-"}KB
                </dd>
                {(detail.gps_lat !== null || detail.gps_lon !== null) && (
                  <>
                    <dt>GPS</dt>
                    <dd>
                      {detail.gps_lat?.toFixed(6)}, {detail.gps_lon?.toFixed(6)}
                    </dd>
                  </>
                )}
                <dt>SHA-256</dt>
                <dd style={{ fontSize: 10, color: "var(--text-dim)" }}>
                  {detail.sha256.slice(0, 12)}…
                </dd>
                <dt>pHash</dt>
                <dd style={{ fontSize: 10, color: "var(--text-dim)" }}>
                  {detail.phash ?? "-"}
                </dd>
                <dt>경로 ({detail.paths.length})</dt>
                <dd style={{ fontSize: 10, display: "flex", flexDirection: "column", gap: 4 }}>
                  {detail.paths.map((p) => (
                    <label
                      key={p.id}
                      style={{
                        display: "flex",
                        gap: 6,
                        alignItems: "flex-start",
                        cursor: "pointer",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={selectedPaths.has(p.id)}
                        onChange={() => togglePath(p.id)}
                      />
                      <span style={{ flex: 1, wordBreak: "break-all" }}>
                        <span style={{ color: "var(--text-dim)" }}>[{p.nas_id}] </span>
                        {p.path}
                      </span>
                    </label>
                  ))}
                  {selectedPaths.size > 0 && (
                    <button
                      type="button"
                      onClick={deleteSelectedPaths}
                      disabled={busy}
                      style={{
                        marginTop: 4,
                        padding: "3px 8px",
                        fontSize: 11,
                        background: "var(--danger)",
                        alignSelf: "flex-start",
                      }}
                    >
                      선택 경로 {selectedPaths.size}개 삭제
                    </button>
                  )}
                </dd>
              </dl>

              <button
                className="ghost"
                onClick={deletePhoto}
                disabled={busy}
                style={{
                  marginTop: 14,
                  background: "var(--danger)",
                  color: "white",
                }}
              >
                이 사진 삭제
              </button>

              <button
                className="ghost"
                onClick={findSimilar}
                disabled={busy || !detail.phash}
                style={{ marginTop: 14 }}
                title={!detail.phash ? "phash가 없는 사진" : ""}
              >
                비슷한 사진 찾기 (pHash)
              </button>

              {similar && (
                <div style={{ marginTop: 12 }}>
                  <h4 style={{ margin: "6px 0", fontSize: 12 }}>
                    pHash 유사 ({similar.length})
                  </h4>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(3, 1fr)",
                      gap: 4,
                    }}
                  >
                    {similar.map((s) => (
                      <div key={s.id} style={{ position: "relative" }}>
                        <img
                          src={s.thumb_url}
                          alt={`#${s.id}`}
                          style={{ width: "100%", aspectRatio: 1, objectFit: "cover", borderRadius: 4 }}
                        />
                        <span
                          style={{
                            position: "absolute",
                            bottom: 2,
                            right: 2,
                            background: "rgba(0,0,0,0.7)",
                            color: "white",
                            fontSize: 10,
                            padding: "1px 4px",
                            borderRadius: 3,
                          }}
                        >
                          {s.hamming}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
        <div className="close" onClick={onClose}>
          ×
        </div>
      </div>
    </div>
  );
}

function UserScoreEditor({
  current,
  onSet,
  disabled,
}: {
  current: number | null;
  onSet: (score: number | null) => void;
  disabled: boolean;
}) {
  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
      {[1, 2, 3, 4, 5].map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onSet(v)}
          disabled={disabled}
          style={{
            padding: "2px 8px",
            fontSize: 11,
            background: current === v ? "var(--accent)" : "var(--panel)",
            color: current === v ? "white" : "var(--text)",
            border: "1px solid var(--border)",
          }}
        >
          {v}
        </button>
      ))}
      {current !== null && (
        <button
          type="button"
          onClick={() => onSet(null)}
          disabled={disabled}
          style={{
            padding: "2px 8px",
            fontSize: 11,
            background: "var(--panel)",
            color: "var(--text-dim)",
            border: "1px solid var(--border)",
          }}
        >
          제거
        </button>
      )}
    </div>
  );
}
