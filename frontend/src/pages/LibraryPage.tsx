import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type PhotoSummary, type QueueCounts } from "../api";
import { PhotoModal } from "./PhotoModal";
import { PromptDialog } from "./PromptDialog";

const SORT_OPTIONS = [
  { value: "-taken_at", label: "촬영일 ↓" },
  { value: "taken_at", label: "촬영일 ↑" },
  { value: "-score", label: "미학 점수 ↓" },
  { value: "score", label: "미학 점수 ↑" },
  { value: "-prompt", label: "prompt 점수 ↓" },
  { value: "prompt", label: "prompt 점수 ↑" },
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
  const [showPrompt, setShowPrompt] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchActive, setSearchActive] = useState(false);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.photos.list({ min_score: minScore, sort, limit: 200 });
      setPhotos(res.items);
      setTotal(res.total);
      setSearchActive(false);
    } finally {
      setLoading(false);
    }
  }, [minScore, sort]);

  const runSearch = useCallback(async () => {
    const q = searchQuery.trim();
    if (!q) {
      setSearchActive(false);
      void fetchList();
      return;
    }
    setLoading(true);
    setSearchActive(true);
    try {
      const res = await api.photos.search(q, 100);
      // search 응답은 PhotoSummary 호환 — 부족 필드 보강
      const items: PhotoSummary[] = res.items.map((it) => ({
        id: it.id,
        sha256: "",
        taken_at: it.taken_at,
        camera_make: null,
        camera_model: it.camera_model,
        lens_model: null,
        iso: null,
        aperture: null,
        shutter: null,
        focal_mm: null,
        gps_lat: null,
        gps_lon: null,
        width: it.width,
        height: it.height,
        size_bytes: 0,
        score: null,
        raw_score: null,
        eval_model_id: null,
        prompt_score: it.similarity,
        prompt_raw: it.similarity,
        thumb_url: it.thumb_url,
      }));
      setPhotos(items);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  }, [searchQuery, fetchList]);

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
    const folder = window.prompt("로컬 폴더 절대경로:");
    if (!folder) return;
    try {
      await api.scan.local(folder);
      alert("로컬 스캔이 백그라운드로 시작되었습니다.");
    } catch (e) {
      alert(`실패: ${e instanceof Error ? e.message : e}`);
    }
  };

  const triggerNasScan = async () => {
    let nasStatus;
    try {
      nasStatus = await api.nas.status();
    } catch (e) {
      alert(`NAS 상태 조회 실패: ${e instanceof Error ? e.message : e}`);
      return;
    }
    if (!nasStatus.configured) {
      alert(
        "NAS가 아직 설정되지 않았습니다.\n" +
          "PowerShell에서 'python -m scripts.nas_login --url http://NAS:5000 --user <USER>'을 먼저 실행하세요.",
      );
      return;
    }
    const folder = window.prompt(
      `NAS 폴더 절대경로 (예: /photo/My Pictures-2023):\n계정: ${nasStatus.username} @ ${nasStatus.base_url}`,
      "/photo",
    );
    if (!folder) return;
    try {
      await api.scan.dsm(folder);
      alert("NAS 스캔이 백그라운드로 시작되었습니다.");
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
            로컬 스캔
          </button>
          <button className="ghost" onClick={triggerNasScan}>
            NAS 스캔
          </button>
          <button className="ghost" onClick={() => setShowPrompt(true)}>
            평가 prompt
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
        <label style={{ flex: "1 1 280px", minWidth: 240 }}>
          시맨틱 검색 (CLIP)
          <input
            type="search"
            placeholder='예: "석양 풍경", "portrait with bokeh"'
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runSearch();
            }}
            style={{ width: "100%" }}
          />
        </label>
        <label>
          최소 점수
          <select
            value={String(minScore)}
            onChange={(e) => setMinScore(parseFloat(e.target.value))}
            disabled={searchActive}
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
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            disabled={searchActive}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        {searchActive && (
          <button
            className="ghost"
            onClick={() => {
              setSearchQuery("");
              void fetchList();
            }}
          >
            검색 종료
          </button>
        )}
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

      {showPrompt && (
        <PromptDialog
          onClose={() => setShowPrompt(false)}
          onSaved={() => {
            setShowPrompt(false);
            void fetchList();
          }}
        />
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
