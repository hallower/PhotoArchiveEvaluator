import { useEffect, useState } from "react";
import { api, type AdvancedReview, type PhotoDetail } from "../api";

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
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [advReviews, setAdvReviews] = useState<AdvancedReview[]>([]);

  const loadReviews = () => api.advanced.listReviews(photoId).then(setAdvReviews).catch(() => {});

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
    void loadReviews();
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
              {aest?.caption && (
                <p
                  style={{
                    background: "var(--panel)",
                    padding: 8,
                    borderRadius: 4,
                    fontSize: 12,
                    color: "var(--text)",
                    margin: "0 0 10px 0",
                    fontStyle: "italic",
                  }}
                >
                  "{aest.caption}"
                </p>
              )}
              {detail.tags.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 10 }}>
                  {detail.tags.map((t) => (
                    <span
                      key={t.name}
                      title={`confidence ${t.confidence.toFixed(3)}`}
                      style={{
                        background: "var(--panel)",
                        border: "1px solid var(--border)",
                        borderRadius: 12,
                        padding: "2px 8px",
                        fontSize: 10,
                        color: "var(--text-dim)",
                      }}
                    >
                      {t.name}
                    </span>
                  ))}
                </div>
              )}
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

              <button
                onClick={() => setShowAdvanced(true)}
                disabled={busy}
                style={{ marginTop: 8 }}
              >
                고급 평가 (Claude vision)
              </button>

              {advReviews.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <h4 style={{ margin: "6px 0", fontSize: 12 }}>
                    고급 평가 이력 ({advReviews.length})
                  </h4>
                  {advReviews.slice(0, 3).map((r) => (
                    <div
                      key={r.id}
                      style={{
                        background: "var(--panel)",
                        padding: 8,
                        borderRadius: 4,
                        marginBottom: 4,
                        fontSize: 11,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span style={{ color: "var(--text-dim)" }}>{r.model_id}</span>
                        <span style={{ color: "var(--text-dim)" }}>
                          ${r.cost_usd?.toFixed(4) ?? "-"}
                        </span>
                      </div>
                      <div style={{ marginTop: 4, whiteSpace: "pre-wrap", color: "var(--text)" }}>
                        {r.response.length > 240
                          ? r.response.slice(0, 240) + "…"
                          : r.response}
                      </div>
                    </div>
                  ))}
                </div>
              )}

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

      {showAdvanced && (
        <AdvancedReviewDialog
          photoId={photoId}
          onClose={() => setShowAdvanced(false)}
          onDone={() => {
            setShowAdvanced(false);
            void loadReviews();
          }}
        />
      )}
    </div>
  );
}

function AdvancedReviewDialog({
  photoId,
  onClose,
  onDone,
}: {
  photoId: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [defaultPrompt, setDefaultPrompt] = useState("");
  const [model, setModel] = useState("claude-sonnet-4-6");
  const [costEstimate, setCostEstimate] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<string | null>(null);

  useEffect(() => {
    void api.settings.get().then((s) => {
      setPrompt(s.default_advanced_prompt);
      setDefaultPrompt(s.default_advanced_prompt);
      setModel(s.external_default_model);
    });
  }, []);

  useEffect(() => {
    void api.advanced.costPreview(photoId, model).then((r) => {
      setCostEstimate(r.cost_usd_estimate);
    });
  }, [photoId, model]);

  const run = async () => {
    setBusy(true);
    setError(null);
    setResponse(null);
    try {
      const r = await api.advanced.review(photoId, prompt, model);
      setResponse(r.response);
      // 약간 후 닫기 — 사용자가 결과를 읽을 시간
      setTimeout(onDone, 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-bg" onClick={onClose} style={{ zIndex: 200 }}>
      <div
        className="modal"
        style={{
          maxWidth: 640,
          flexDirection: "column",
          padding: 22,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: "0 0 12px 0" }}>고급 평가 (Claude vision)</h3>

        <label style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 4 }}>모델</label>
        <select value={model} onChange={(e) => setModel(e.target.value)} disabled={busy}>
          <option value="claude-haiku-4-5">claude-haiku-4-5 (저렴)</option>
          <option value="claude-sonnet-4-6">claude-sonnet-4-6 (균형)</option>
          <option value="claude-opus-4-7">claude-opus-4-7 (최고)</option>
        </select>

        <label style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 12, marginBottom: 4 }}>
          프롬프트 (영어 권장)
        </label>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={6}
          disabled={busy}
          style={{
            background: "var(--panel)",
            color: "var(--text)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: 10,
            font: "inherit",
            resize: "vertical",
          }}
        />
        <button
          type="button"
          className="ghost"
          onClick={() => setPrompt(defaultPrompt)}
          disabled={busy}
          style={{ marginTop: 4, alignSelf: "flex-start", fontSize: 11 }}
        >
          기본값 복원
        </button>

        <div
          style={{
            marginTop: 12,
            background: "var(--panel)",
            padding: 8,
            borderRadius: 4,
            fontSize: 12,
            color: "var(--text-dim)",
          }}
        >
          예상 비용:{" "}
          <strong style={{ color: "var(--text)" }}>
            {costEstimate !== null ? `$${costEstimate.toFixed(4)}` : "..."}
          </strong>{" "}
          (1회 호출 기준 — 실제 비용은 응답 후 기록)
        </div>

        {response && (
          <div
            style={{
              marginTop: 12,
              background: "var(--panel-2)",
              padding: 10,
              borderRadius: 4,
              fontSize: 12,
              whiteSpace: "pre-wrap",
              maxHeight: 200,
              overflowY: "auto",
            }}
          >
            {response}
          </div>
        )}

        {error && (
          <div style={{ color: "var(--danger)", marginTop: 10, fontSize: 12 }}>
            {error}
          </div>
        )}

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 14,
          }}
        >
          <button className="ghost" onClick={onClose} disabled={busy}>취소</button>
          <button onClick={run} disabled={busy || !prompt.trim()}>
            {busy ? "분석 중..." : "고급 평가 실행"}
          </button>
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
