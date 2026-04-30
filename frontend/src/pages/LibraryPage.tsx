import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type PhotoSummary, type QueueCounts } from "../api";
import { PhotoModal } from "./PhotoModal";

const SORT_OPTIONS = [
  { value: "-taken_at", label: "촬영일 ↓" },
  { value: "taken_at", label: "촬영일 ↑" },
  { value: "-score", label: "점수 ↓" },
  { value: "score", label: "점수 ↑" },
  { value: "-id", label: "최근 등록" },
];

export function LibraryPage({ onLogout }: { onLogout: () => void }) {
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [minScore, setMinScore] = useState<number>(4.0);
  const [sort, setSort] = useState<string>("-taken_at");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [queue, setQueue] = useState<QueueCounts | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.photos.list({ min_score: minScore, sort, limit: 200 });
      setPhotos(res.items);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  }, [minScore, sort]);

  const fetchQueue = useCallback(async () => {
    try {
      setQueue(await api.eval.queue());
    } catch {
      // 무시 — 인증 만료 등은 상위 App에서 처리
    }
  }, []);

  useEffect(() => {
    void fetchList();
  }, [fetchList]);

  useEffect(() => {
    void fetchQueue();
    const id = setInterval(() => void fetchQueue(), 5000);
    return () => clearInterval(id);
  }, [fetchQueue]);

  const triggerScan = async () => {
    const folder = window.prompt("스캔할 폴더 절대경로:");
    if (!folder) return;
    try {
      await api.scan.local(folder);
      alert("스캔이 백그라운드로 시작되었습니다.");
    } catch (e) {
      alert(`실패: ${e instanceof Error ? e.message : e}`);
    }
  };

  const triggerEval = async () => {
    try {
      await api.eval.process(null);
      alert("평가 워커가 시작되었습니다. 완료되면 목록을 새로고침해 주세요.");
    } catch (e) {
      alert(`실패: ${e instanceof Error ? e.message : e}`);
    }
  };

  return (
    <div className="app">
      <header className="header">
        <h1>Photo Archive Evaluator</h1>
        <div className="header-right">
          <button className="ghost" onClick={triggerScan}>
            스캔
          </button>
          <button className="ghost" onClick={triggerEval}>
            평가 처리
          </button>
          <button className="ghost" onClick={fetchList}>
            새로고침
          </button>
          <button className="ghost" onClick={onLogout}>
            로그아웃
          </button>
        </div>
      </header>
      <div className="toolbar">
        <label>
          최소 점수
          <select
            value={String(minScore)}
            onChange={(e) => setMinScore(parseFloat(e.target.value))}
          >
            <option value="0">전체</option>
            <option value="3">3 이상</option>
            <option value="3.5">3.5 이상</option>
            <option value="4">4 이상 (기본)</option>
            <option value="4.5">4.5 이상</option>
            <option value="5">5만</option>
          </select>
        </label>
        <label>
          정렬
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <div className="stats">
          <div>
            결과: <span className="stat-num">{total}</span>장
          </div>
          {queue && (
            <div>
              큐: 대기 <span className="stat-num">{queue.pending}</span> / 처리중{" "}
              <span className="stat-num">{queue.in_progress}</span> / 완료{" "}
              <span className="stat-num">{queue.done}</span>
              {queue.failed > 0 && (
                <span style={{ color: "var(--danger)" }}>
                  {" "}/ 실패 <span className="stat-num">{queue.failed}</span>
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {loading && photos.length === 0 ? (
        <div className="empty">불러오는 중...</div>
      ) : photos.length === 0 ? (
        <div className="empty">조건에 맞는 사진이 없습니다.</div>
      ) : (
        <div className="grid">
          {photos.map((p) => (
            <Card key={p.id} photo={p} onClick={() => setSelected(p.id)} />
          ))}
        </div>
      )}

      {selected !== null && (
        <PhotoModal photoId={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function Card({ photo, onClick }: { photo: PhotoSummary; onClick: () => void }) {
  const scoreClass = useMemo(() => {
    if (photo.score === null) return "score-1";
    return `score-${Math.max(1, Math.min(5, Math.round(photo.score)))}`;
  }, [photo.score]);

  return (
    <div className="card" onClick={onClick}>
      <img src={photo.thumb_url} alt={`photo ${photo.id}`} className="thumb" loading="lazy" />
      {photo.score !== null && (
        <div className={`score-badge ${scoreClass}`}>{photo.score.toFixed(1)}</div>
      )}
      <div className="info">
        <span>{photo.camera_model ?? "-"}</span>
        <span>
          {photo.taken_at ? new Date(photo.taken_at).toLocaleDateString("ko-KR") : "-"}
        </span>
      </div>
    </div>
  );
}
