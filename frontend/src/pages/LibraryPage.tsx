import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type PhotoSummary, type PortfolioSummary, type QueueCounts } from "../api";
import { ContestsPage } from "./ContestsPage";
import { PhotoModal } from "./PhotoModal";
import { PortfoliosPage } from "./PortfoliosPage";
import { SettingsPage } from "./SettingsPage";

const SORT_OPTIONS = [
  { value: "-taken_at", label: "촬영일 ↓" },
  { value: "taken_at", label: "촬영일 ↑" },
  { value: "-final", label: "점수 ↓ (사용자 우선)" },
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
  const [sort, setSort] = useState<string>("-score");
  const [loading, setLoading] = useState(false);
  const [openPhotoId, setOpenPhotoId] = useState<number | null>(null);
  const [queue, setQueue] = useState<QueueCounts | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchActive, setSearchActive] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [selected, setSelectedSet] = useState<Set<number>>(new Set());
  const [showPortfolios, setShowPortfolios] = useState(false);
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([]);
  const [showContests, setShowContests] = useState(false);

  const toggleSelected = (id: number) =>
    setSelectedSet((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const clearSelection = () => setSelectedSet(new Set());
  const selectAll = () => setSelectedSet(new Set(photos.map((p) => p.id)));

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.photos.list({
        min_score: minScore,
        sort,
        limit: 200,
        q: keyword.trim() || undefined,
      });
      setPhotos(res.items);
      setTotal(res.total);
      setSearchActive(false);
    } finally {
      setLoading(false);
    }
  }, [minScore, sort, keyword]);

  // 첫 진입 시 settings에서 임계값 로드
  useEffect(() => {
    void api.settings
      .get()
      .then((s) => setMinScore(s.library_min_score))
      .catch(() => {});
  }, []);

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
        user_score: null,
        final_score: it.similarity,
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

  const refreshPortfolios = useCallback(() => {
    void api.portfolios.list().then(setPortfolios).catch(() => {});
  }, []);

  useEffect(() => {
    refreshPortfolios();
  }, [refreshPortfolios]);

  const bulkDelete = async () => {
    if (selected.size === 0) return;
    const deleteFiles = window.confirm(
      `${selected.size}개 사진을 라이브러리에서 삭제합니다.\n\n` +
        "확인을 누르면: DB 레코드 + 썸네일 캐시 삭제 (NAS/디스크 원본 보존)\n" +
        "취소를 누르면 작업 중단",
    );
    if (!deleteFiles) return;
    const alsoFiles = window.confirm(
      "추가로 로컬 디스크의 원본 파일까지 삭제할까요?\n" +
        "확인 = 로컬 원본 파일 삭제 (NAS는 항상 보존)\n" +
        "취소 = DB만 삭제",
    );
    try {
      const r = await api.photos.bulkDelete([...selected], alsoFiles);
      alert(
        `삭제됨: ${r.deleted}장${alsoFiles ? `, 파일 삭제: ${r.files_deleted}` : ""}`,
      );
      clearSelection();
      void fetchList();
    } catch (e) {
      alert(`실패: ${e instanceof Error ? e.message : e}`);
    }
  };

  const addToPortfolio = async () => {
    if (selected.size === 0) return;
    let target: number | "new" | null = null;
    if (portfolios.length === 0) {
      target = "new";
    } else {
      const choices = portfolios
        .map((p, i) => `${i + 1}. ${p.name} (${p.count})`)
        .join("\n");
      const ans = window.prompt(
        `포트폴리오 선택 (번호 입력, 새로 만들려면 "new"):\n\n${choices}`,
        "new",
      );
      if (!ans) return;
      if (ans.trim().toLowerCase() === "new") target = "new";
      else {
        const idx = parseInt(ans, 10) - 1;
        if (Number.isNaN(idx) || idx < 0 || idx >= portfolios.length) {
          alert("잘못된 입력");
          return;
        }
        target = portfolios[idx].id;
      }
    }
    try {
      if (target === "new") {
        const name = window.prompt("새 포트폴리오 이름:");
        if (!name?.trim()) return;
        await api.portfolios.create(name.trim(), undefined, [...selected]);
        alert(`"${name}" 포트폴리오 생성됨 (${selected.size}장)`);
      } else if (typeof target === "number") {
        const r = await api.portfolios.addItems(target, [...selected]);
        alert(`${r.added}장 추가됨`);
      }
      clearSelection();
      refreshPortfolios();
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
          <button className="ghost" onClick={() => setShowPortfolios(true)}>
            포트폴리오
          </button>
          <button className="ghost" onClick={() => setShowContests(true)}>
            공모전
          </button>
          <button className="ghost" onClick={() => setShowSettings(true)}>
            설정
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
        <label style={{ flex: "1 1 240px", minWidth: 200 }}>
          시맨틱 검색 (CLIP)
          <input
            type="search"
            placeholder='예: "portrait with bokeh"'
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runSearch();
            }}
            style={{ width: "100%" }}
          />
        </label>
        <label style={{ flex: "1 1 200px", minWidth: 160 }}>
          키워드 (카메라/렌즈/경로)
          <input
            type="search"
            placeholder='예: "X-E4", "2018"'
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void fetchList();
            }}
            disabled={searchActive}
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

      {selected.size > 0 && (
        <div
          style={{
            background: "var(--accent)",
            color: "white",
            padding: "10px 20px",
            display: "flex",
            gap: 12,
            alignItems: "center",
            position: "sticky",
            top: 50,
            zIndex: 9,
          }}
        >
          <span style={{ fontWeight: 600 }}>{selected.size}개 선택됨</span>
          <button className="ghost" onClick={selectAll}>현재 페이지 전체</button>
          <button className="ghost" onClick={clearSelection}>선택 해제</button>
          <span style={{ flex: 1 }} />
          <button className="ghost" onClick={addToPortfolio}>포트폴리오에 추가</button>
          <button
            onClick={bulkDelete}
            style={{ background: "var(--danger)" }}
          >
            삭제
          </button>
        </div>
      )}

      {loading && photos.length === 0 ? (
        <div className="empty">불러오는 중...</div>
      ) : photos.length === 0 ? (
        <div className="empty">조건에 맞는 사진이 없습니다.</div>
      ) : (
        <div className="grid">
          {photos.map((p) => (
            <Card
              key={p.id}
              photo={p}
              isSelected={selected.has(p.id)}
              onToggleSelect={() => toggleSelected(p.id)}
              onClick={() => setOpenPhotoId(p.id)}
            />
          ))}
        </div>
      )}

      {openPhotoId !== null && (
        <PhotoModal
          photoId={openPhotoId}
          onClose={() => {
            setOpenPhotoId(null);
            void fetchList();
          }}
        />
      )}

      {showPortfolios && (
        <PortfoliosPage
          portfolios={portfolios}
          onClose={() => {
            setShowPortfolios(false);
            refreshPortfolios();
          }}
          onRefresh={refreshPortfolios}
          onOpenPhoto={(id) => setOpenPhotoId(id)}
        />
      )}

      {showSettings && (
        <SettingsPage
          onClose={() => {
            setShowSettings(false);
            void fetchList();
          }}
        />
      )}

      {showContests && (
        <ContestsPage
          onClose={() => {
            setShowContests(false);
            refreshPortfolios();
          }}
          onOpenPhoto={(id) => setOpenPhotoId(id)}
        />
      )}
    </div>
  );
}

function Card({
  photo,
  isSelected,
  onClick,
  onToggleSelect,
}: {
  photo: PhotoSummary;
  isSelected: boolean;
  onClick: () => void;
  onToggleSelect: () => void;
}) {
  const displayScore = photo.final_score ?? photo.score;
  const userOverride = photo.user_score !== null && photo.user_score !== undefined;

  const scoreClass = useMemo(() => {
    if (displayScore === null || displayScore === undefined) return "score-1";
    return `score-${Math.max(1, Math.min(5, Math.round(displayScore)))}`;
  }, [displayScore]);

  return (
    <div
      className="card"
      onClick={onClick}
      style={isSelected ? { borderColor: "var(--accent)", boxShadow: "0 0 0 2px var(--accent)" } : {}}
    >
      <img src={photo.thumb_url} alt={`photo ${photo.id}`} className="thumb" loading="lazy" />
      <div
        onClick={(e) => {
          e.stopPropagation();
          onToggleSelect();
        }}
        title={isSelected ? "선택 해제" : "선택"}
        style={{
          position: "absolute",
          top: 6,
          left: 6,
          width: 22,
          height: 22,
          borderRadius: 4,
          background: isSelected ? "var(--accent)" : "rgba(0, 0, 0, 0.5)",
          color: "white",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 14,
          fontWeight: 700,
          cursor: "pointer",
          border: "1px solid rgba(255, 255, 255, 0.3)",
        }}
      >
        {isSelected ? "✓" : ""}
      </div>
      {displayScore !== null && displayScore !== undefined && (
        <div
          className={`score-badge ${scoreClass}`}
          title={userOverride ? "사용자 점수" : "AI 점수"}
        >
          {userOverride ? "★ " : ""}
          {displayScore.toFixed(1)}
        </div>
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
