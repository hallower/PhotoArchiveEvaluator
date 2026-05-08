import { useEffect, useState } from "react";
import { api, type AdvancedReview, type ExternalModel, type PhotoDetail } from "../api";

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
  const [showReviewsModal, setShowReviewsModal] = useState(false);

  const loadReviews = () => api.advanced.listReviews(photoId).then(setAdvReviews).catch(() => {});

  const deleteReview = async (id: number) => {
    if (!window.confirm("이 고급 평가 기록을 삭제할까요?")) return;
    try {
      await api.advanced.deleteReview(id);
      await loadReviews();
    } catch (e) {
      alert(`실패: ${e instanceof Error ? e.message : e}`);
    }
  };

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
    if (
      !window.confirm(
        `${selectedPaths.size}개 경로를 라이브러리에서 제거합니다.\n` +
          "원본 파일(로컬·NAS)은 보존됩니다.",
      )
    )
      return;
    setBusy(true);
    try {
      const r = await api.photos.deletePaths(detail.id, [...selectedPaths]);
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
          "DB 레코드(평가/임베딩/썸네일/태그/포트폴리오 항목)만 삭제 — 원본 파일은 보존됩니다.",
      )
    )
      return;
    setBusy(true);
    try {
      await api.photos.bulkDelete([detail.id]);
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
                  {aest?.ai_score?.toFixed(3) ?? "-"}
                  <span style={{ color: "var(--text-dim)" }}> /100</span>
                  {aest?.raw_score !== null && aest?.raw_score !== undefined && (
                    <span style={{ color: "var(--text-dim)", fontSize: 10 }}>
                      {" "}(raw {aest.raw_score.toFixed(2)})
                    </span>
                  )}
                </dd>
                <dt>prompt 점수</dt>
                <dd>
                  {promptEval?.ai_score?.toFixed(3) ?? "-"}
                  <span style={{ color: "var(--text-dim)" }}> /100</span>
                  {promptEval?.raw_score !== null && promptEval?.raw_score !== undefined && (
                    <span style={{ color: "var(--text-dim)", fontSize: 10 }}>
                      {" "}(sim {promptEval.raw_score.toFixed(3)})
                    </span>
                  )}
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
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      margin: "6px 0",
                    }}
                  >
                    <h4 style={{ margin: 0, fontSize: 12 }}>
                      고급 평가 이력 ({advReviews.length})
                    </h4>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setShowReviewsModal(true)}
                      style={{ fontSize: 11, padding: "3px 8px" }}
                    >
                      전체 보기
                    </button>
                  </div>
                  {advReviews.slice(0, 2).map((r) => (
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
                      <div
                        style={{
                          marginTop: 4,
                          whiteSpace: "pre-wrap",
                          color: "var(--text)",
                          maxHeight: 120,
                          overflowY: "auto",
                        }}
                      >
                        {r.response}
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

      {showReviewsModal && (
        <AdvancedReviewsListModal
          reviews={advReviews}
          onClose={() => setShowReviewsModal(false)}
          onDelete={deleteReview}
        />
      )}
    </div>
  );
}

function AdvancedReviewsListModal({
  reviews,
  onClose,
  onDelete,
}: {
  reviews: AdvancedReview[];
  onClose: () => void;
  onDelete: (id: number) => void;
}) {
  // 리뷰별 번역 상태: id → { busy, text, error }
  const [translations, setTranslations] = useState<
    Record<number, { busy: boolean; text?: string; error?: string }>
  >({});

  const translate = async (id: number, source: string) => {
    setTranslations((prev) => ({ ...prev, [id]: { busy: true } }));
    try {
      const r = await api.advanced.translate(source);
      setTranslations((prev) => ({
        ...prev,
        [id]: { busy: false, text: r.translated },
      }));
    } catch (e) {
      setTranslations((prev) => ({
        ...prev,
        [id]: { busy: false, error: e instanceof Error ? e.message : String(e) },
      }));
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-bg" onClick={onClose} style={{ zIndex: 200 }}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{
          flexDirection: "column",
          maxWidth: 820,
          width: "100%",
          maxHeight: "90vh",
          padding: 0,
        }}
      >
        <div
          style={{
            padding: "14px 18px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flex: "0 0 auto",
          }}
        >
          <h3 style={{ margin: 0, fontSize: 14 }}>
            고급 평가 이력 ({reviews.length})
          </h3>
          <button className="ghost" onClick={onClose} style={{ fontSize: 12 }}>
            닫기
          </button>
        </div>
        <div
          style={{
            padding: 14,
            overflowY: "auto",
            flex: "1 1 auto",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          {reviews.length === 0 && (
            <div className="empty">고급 평가 기록이 없습니다.</div>
          )}
          {reviews.map((r) => {
            const tr = translations[r.id];
            return (
              <div
                key={r.id}
                style={{
                  background: "var(--panel-2)",
                  border: "1px solid var(--border)",
                  padding: 12,
                  borderRadius: 6,
                  fontSize: 12,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 8,
                    flexWrap: "wrap",
                    gap: 8,
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    <span style={{ color: "var(--text)", fontWeight: 600 }}>
                      {r.model_id}
                    </span>
                    <span style={{ color: "var(--text-dim)", fontSize: 10 }}>
                      {new Date(r.created_at).toLocaleString("ko-KR")}
                    </span>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      color: "var(--text-dim)",
                      fontSize: 11,
                    }}
                  >
                    <span>
                      ${r.cost_usd?.toFixed(4) ?? "-"}
                      {r.tokens_in !== null && r.tokens_out !== null && (
                        <> · {r.tokens_in}/{r.tokens_out} tok</>
                      )}
                    </span>
                    <button
                      type="button"
                      onClick={() => translate(r.id, r.response)}
                      disabled={tr?.busy}
                      style={{
                        padding: "2px 8px",
                        fontSize: 10,
                        background: tr?.text ? "var(--panel)" : "var(--accent)",
                        color: "white",
                        border: "1px solid var(--border)",
                      }}
                    >
                      {tr?.busy ? "번역 중..." : tr?.text ? "다시 번역" : "한글 번역"}
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(r.id)}
                      style={{
                        padding: "2px 8px",
                        fontSize: 10,
                        background: "var(--panel)",
                        color: "var(--text-dim)",
                        border: "1px solid var(--border)",
                      }}
                    >
                      삭제
                    </button>
                  </div>
                </div>
                {r.prompt && (
                  <details style={{ marginBottom: 8 }}>
                    <summary
                      style={{
                        color: "var(--text-dim)",
                        fontSize: 10,
                        cursor: "pointer",
                      }}
                    >
                      프롬프트 보기
                    </summary>
                    <div
                      style={{
                        marginTop: 4,
                        padding: 8,
                        background: "var(--panel)",
                        borderRadius: 4,
                        whiteSpace: "pre-wrap",
                        color: "var(--text-dim)",
                        fontSize: 11,
                      }}
                    >
                      {r.prompt}
                    </div>
                  </details>
                )}
                <div
                  style={{
                    whiteSpace: "pre-wrap",
                    color: "var(--text)",
                    lineHeight: 1.55,
                  }}
                >
                  {r.response}
                </div>
                {tr?.text && (
                  <div
                    style={{
                      marginTop: 10,
                      padding: 10,
                      background: "var(--panel)",
                      borderLeft: "3px solid var(--accent)",
                      borderRadius: 4,
                      whiteSpace: "pre-wrap",
                      color: "var(--text)",
                      lineHeight: 1.55,
                    }}
                  >
                    <div
                      style={{
                        fontSize: 10,
                        color: "var(--text-dim)",
                        marginBottom: 6,
                        fontWeight: 600,
                      }}
                    >
                      한글 번역
                    </div>
                    {tr.text}
                  </div>
                )}
                {tr?.error && (
                  <div
                    style={{
                      marginTop: 8,
                      color: "var(--danger)",
                      fontSize: 11,
                    }}
                  >
                    번역 실패: {tr.error}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
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
  const [models, setModels] = useState<ExternalModel[]>([]);
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
    void api.advanced.models().then((r) => setModels(r.models)).catch(() => {});
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
          {models.length === 0 ? (
            <option value={model}>{model}</option>
          ) : (
            models.map((m) => (
              <option key={m.id} value={m.id}>
                [{m.provider}] {m.id} (${m.input_price_per_million}/M in, ${m.output_price_per_million}/M out)
              </option>
            ))
          )}
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
  const [draft, setDraft] = useState<string>(
    current !== null ? current.toFixed(3) : "",
  );

  useEffect(() => {
    setDraft(current !== null ? current.toFixed(3) : "");
  }, [current]);

  const commit = () => {
    if (draft.trim() === "") return;
    const v = parseFloat(draft);
    if (Number.isNaN(v)) return;
    const clamped = Math.max(0, Math.min(100, v));
    onSet(parseFloat(clamped.toFixed(3)));
  };

  const presets = [50, 70, 80, 90, 100];

  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
      <input
        type="number"
        min={0}
        max={100}
        step={0.001}
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
        placeholder="0–100"
        style={{ width: 90, fontSize: 11, padding: "2px 6px" }}
      />
      <span style={{ color: "var(--text-dim)", fontSize: 10 }}>/100</span>
      {presets.map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onSet(v)}
          disabled={disabled}
          style={{
            padding: "2px 6px",
            fontSize: 10,
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
            fontSize: 10,
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
