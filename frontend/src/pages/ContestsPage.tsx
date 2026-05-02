import { useEffect, useState } from "react";
import { api, type ContestMatches, type ContestSummary } from "../api";

export function ContestsPage({
  onClose,
  onOpenPhoto,
}: {
  onClose: () => void;
  onOpenPhoto: (id: number) => void;
}) {
  const [contests, setContests] = useState<ContestSummary[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  const refresh = () => api.contests.list().then(setContests).catch(() => {});

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="modal-bg" onClick={onClose}>
      <div
        className="modal"
        style={{
          maxWidth: 900,
          flexDirection: "column",
          padding: 20,
          maxHeight: "92vh",
          overflowY: "auto",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>공모전</h2>
          <button onClick={() => setCreating(true)}>신규 공모전</button>
        </div>

        {contests.length === 0 ? (
          <div style={{ color: "var(--text-dim)", padding: 30, textAlign: "center" }}>
            공모전이 없습니다. "신규 공모전"으로 등록하세요.
          </div>
        ) : (
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
            {contests.map((c) => (
              <div
                key={c.id}
                onClick={() => setOpenId(c.id)}
                style={{
                  background: "var(--panel-2)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  padding: 12,
                  cursor: "pointer",
                }}
              >
                <div style={{ fontWeight: 600 }}>{c.name}</div>
                <div style={{ color: "var(--text-dim)", fontSize: 11, marginTop: 4 }}>
                  주제 {c.themes.length}개 · {c.themes.slice(0, 4).join(" / ") || "(없음)"}
                  {c.themes.length > 4 ? " ..." : ""}
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
          <button className="ghost" onClick={onClose}>닫기</button>
        </div>
      </div>

      {openId !== null && (
        <ContestDetail
          contestId={openId}
          onClose={() => {
            setOpenId(null);
            void refresh();
          }}
          onOpenPhoto={onOpenPhoto}
        />
      )}

      {creating && (
        <ContestCreate
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            void refresh();
            setOpenId(id);
          }}
        />
      )}
    </div>
  );
}

function ContestCreate({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const [name, setName] = useState("");
  const [info, setInfo] = useState("");
  const [themesText, setThemesText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.contests.analyze(info);
      setThemesText(r.themes.join("\n"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const themes = themesText
        .split("\n")
        .map((t) => t.trim())
        .filter((t) => t);
      const c = await api.contests.create(name.trim(), info || null, themes);
      onCreated(c.id);
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
        style={{ maxWidth: 640, flexDirection: "column", padding: 22, maxHeight: "92vh", overflowY: "auto" }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: "0 0 12px 0" }}>신규 공모전</h3>

        <label style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 4 }}>공모전 이름</label>
        <input value={name} onChange={(e) => setName(e.target.value)} disabled={busy} />

        <label style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 12, marginBottom: 4 }}>
          공모전 정보 (요강·테마·심사기준 등 자유롭게)
        </label>
        <textarea
          value={info}
          onChange={(e) => setInfo(e.target.value)}
          rows={6}
          disabled={busy}
          style={textareaStyle}
          placeholder="예: '도시의 빛과 사람을 주제로 한 풍경/스트리트 공모전. ...'"
        />

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button
            type="button"
            className="ghost"
            onClick={analyze}
            disabled={busy || info.trim().length < 10}
            title="외부 API consent + Anthropic 키가 설정에 등록되어 있어야 함"
          >
            AI로 주제 추출 (Claude)
          </button>
        </div>

        <label style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 12, marginBottom: 4 }}>
          주제 (한 줄에 1개, 영어 권장 — CLIP 매칭 정확도)
        </label>
        <textarea
          value={themesText}
          onChange={(e) => setThemesText(e.target.value)}
          rows={6}
          disabled={busy}
          style={textareaStyle}
          placeholder="cityscape with neon lights&#10;portrait in golden hour&#10;..."
        />

        {error && (
          <div style={{ color: "var(--danger)", marginTop: 10, fontSize: 12 }}>{error}</div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
          <button className="ghost" onClick={onClose} disabled={busy}>취소</button>
          <button onClick={create} disabled={busy || !name.trim() || !themesText.trim()}>
            {busy ? "처리 중..." : "생성"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ContestDetail({
  contestId,
  onClose,
  onOpenPhoto,
}: {
  contestId: number;
  onClose: () => void;
  onOpenPhoto: (id: number) => void;
}) {
  const [data, setData] = useState<ContestMatches | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [topN, setTopN] = useState(10);

  const load = (n: number = topN) =>
    api.contests.matches(contestId, n).then(setData).catch(() => setData(null));

  useEffect(() => {
    void load(topN);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contestId]);

  const toggle = (id: number) =>
    setSelected((p) => {
      const n = new Set(p);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const remove = async () => {
    if (!data) return;
    if (!window.confirm(`"${data.contest.name}" 공모전을 삭제할까요?`)) return;
    setBusy(true);
    try {
      await api.contests.remove(data.contest.id);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const makePortfolio = async () => {
    if (!data || selected.size === 0) return;
    const name = window.prompt(
      "포트폴리오 이름:",
      `${data.contest.name} - 후보 ${selected.size}장`,
    );
    if (!name?.trim()) return;
    setBusy(true);
    try {
      await api.contests.makePortfolio(data.contest.id, name.trim(), [...selected]);
      alert(`포트폴리오 "${name}" 생성 (${selected.size}장)`);
      setSelected(new Set());
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return (
      <div className="modal-bg" onClick={onClose} style={{ zIndex: 200 }}>
        <div className="empty">로딩 중...</div>
      </div>
    );
  }

  return (
    <div className="modal-bg" onClick={onClose} style={{ zIndex: 200 }}>
      <div
        className="modal"
        style={{ maxWidth: 1200, flexDirection: "column", padding: 22, maxHeight: "94vh", overflowY: "auto" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 18 }}>{data.contest.name}</h2>
            {data.contest.info_text && (
              <p style={{ color: "var(--text-dim)", fontSize: 12, margin: "4px 0 0 0", maxWidth: 800 }}>
                {data.contest.info_text.slice(0, 200)}
                {data.contest.info_text.length > 200 ? "..." : ""}
              </p>
            )}
          </div>
          <button className="ghost" onClick={remove} disabled={busy} style={{ color: "var(--danger)" }}>
            삭제
          </button>
        </div>

        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 12 }}>
          <label style={{ fontSize: 12, color: "var(--text-dim)" }}>
            주제별 top
            <select
              value={topN}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10);
                setTopN(n);
                void load(n);
              }}
              style={{ marginLeft: 6 }}
            >
              {[5, 10, 15, 20, 30].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <span style={{ flex: 1 }} />
          <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
            {selected.size}장 선택됨
          </span>
          <button onClick={makePortfolio} disabled={busy || selected.size === 0}>
            선택 사진을 포트폴리오로
          </button>
        </div>

        {data.note && (
          <div style={{ color: "var(--text-dim)", padding: 20, textAlign: "center" }}>
            {data.note === "no embeddings"
              ? "아직 임베딩이 없는 사진들입니다. 평가 처리 후 다시 시도하세요."
              : data.note}
          </div>
        )}

        {data.matches.map((m) => (
          <div key={m.theme} style={{ marginTop: 16 }}>
            <h3 style={{ fontSize: 14, margin: "0 0 8px 0" }}>
              <span style={{ color: "var(--accent)" }}>●</span> {m.theme}
            </h3>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
                gap: 6,
              }}
            >
              {m.photos.map((p) => (
                <div
                  key={p.photo_id}
                  style={{
                    position: "relative",
                    border: selected.has(p.photo_id)
                      ? "2px solid var(--accent)"
                      : "1px solid var(--border)",
                    borderRadius: 4,
                    overflow: "hidden",
                  }}
                >
                  <img
                    src={p.thumb_url}
                    alt={`#${p.photo_id}`}
                    onClick={() => onOpenPhoto(p.photo_id)}
                    loading="lazy"
                    style={{
                      width: "100%",
                      aspectRatio: "1",
                      objectFit: "cover",
                      cursor: "pointer",
                      background: "#000",
                    }}
                  />
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(p.photo_id);
                    }}
                    title={selected.has(p.photo_id) ? "선택 해제" : "선택"}
                    style={{
                      position: "absolute",
                      top: 4,
                      left: 4,
                      width: 20,
                      height: 20,
                      borderRadius: 4,
                      background: selected.has(p.photo_id)
                        ? "var(--accent)"
                        : "rgba(0,0,0,0.5)",
                      color: "white",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 13,
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    {selected.has(p.photo_id) ? "✓" : ""}
                  </div>
                  <div
                    style={{
                      position: "absolute",
                      bottom: 4,
                      right: 4,
                      background: "rgba(0,0,0,0.7)",
                      color: "white",
                      fontSize: 10,
                      padding: "1px 5px",
                      borderRadius: 3,
                    }}
                  >
                    {p.similarity.toFixed(3)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
          <button className="ghost" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}

const textareaStyle: React.CSSProperties = {
  background: "var(--panel)",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  padding: 10,
  font: "inherit",
  resize: "vertical",
};
