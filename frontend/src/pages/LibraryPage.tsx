import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type ClusterItem,
  type LibraryItem,
  type PhotoSummary,
  type PortfolioSummary,
  type QueueCounts,
} from "../api";
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
  { value: "-doc", label: "다큐 점수 ↓" },
  { value: "doc", label: "다큐 점수 ↑" },
  { value: "-id", label: "최근 등록" },
];

export function LibraryPage({ onLogout }: { onLogout: () => void }) {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [minScore, setMinScore] = useState<number>(80.0);
  const [sort, setSort] = useState<string>("-doc");
  const [loading, setLoading] = useState(false);
  const [openPhotoId, setOpenPhotoId] = useState<number | null>(null);
  const [openCluster, setOpenCluster] = useState<ClusterItem | null>(null);
  const [queue, setQueue] = useState<QueueCounts | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchActive, setSearchActive] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [advancedFilter, setAdvancedFilter] = useState<"all" | "with" | "without">("all");
  const [clusterMode, setClusterMode] = useState(true);
  const [clusterDistance, setClusterDistance] = useState<number>(8);
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
  const selectAll = () =>
    setSelectedSet(
      new Set(
        items.flatMap((it) =>
          it.type === "cluster" ? it.members.map((m) => m.id) : [it.id],
        ),
      ),
    );

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.photos.list({
        min_score: minScore,
        sort,
        limit: 200,
        q: keyword.trim() || undefined,
        has_advanced:
          advancedFilter === "with" ? true : advancedFilter === "without" ? false : undefined,
        cluster: clusterMode || undefined,
        cluster_distance: clusterMode ? clusterDistance : undefined,
      });
      setItems(res.items);
      setTotal(res.total);
      setSearchActive(false);
    } finally {
      setLoading(false);
    }
  }, [minScore, sort, keyword, advancedFilter, clusterMode, clusterDistance]);

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
      const photos: PhotoSummary[] = res.items.map((it) => ({
        type: "photo",
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
        documentary_score: null,
        documentary_raw: null,
        user_score: null,
        final_score: it.similarity,
        thumb_url: it.thumb_url,
      }));
      setItems(photos);
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
    if (
      !window.confirm(
        `${selected.size}개 사진을 라이브러리에서 삭제합니다.\n\n` +
          "DB 레코드 + 썸네일 캐시만 삭제됩니다 (원본 파일은 보존).\n" +
          "이 사진들이 다음 스캔에서 다시 등록될 수 있습니다.",
      )
    )
      return;
    try {
      const r = await api.photos.bulkDelete([...selected]);
      alert(`삭제됨: ${r.deleted}장 (원본 보존)`);
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
            <option value="40">40 이상</option>
            <option value="60">60 이상</option>
            <option value="70">70 이상</option>
            <option value="80">80 이상 (기본)</option>
            <option value="90">90 이상</option>
            <option value="95">95 이상</option>
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
        <label>
          고급 평가
          <select
            value={advancedFilter}
            onChange={(e) =>
              setAdvancedFilter(e.target.value as "all" | "with" | "without")
            }
            disabled={searchActive}
          >
            <option value="all">전체</option>
            <option value="with">있는 것만</option>
            <option value="without">없는 것만</option>
          </select>
        </label>
        <label style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
          <input
            type="checkbox"
            checked={clusterMode}
            onChange={(e) => setClusterMode(e.target.checked)}
            disabled={searchActive}
            style={{ margin: 0, padding: 0 }}
          />
          <span>유사 사진 묶기</span>
        </label>
        {clusterMode && (
          <label style={{ minWidth: 200 }}>
            유사도 ({clusterDistance})
            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
              }}
            >
              <input
                type="range"
                min={2}
                max={20}
                step={1}
                value={clusterDistance}
                onChange={(e) => setClusterDistance(parseInt(e.target.value, 10))}
                disabled={searchActive}
                style={{ flex: 1, padding: 0 }}
                title={`hamming distance ≤ ${clusterDistance} (작을수록 엄격)`}
              />
              <select
                value={String(clusterDistance)}
                onChange={(e) => setClusterDistance(parseInt(e.target.value, 10))}
                disabled={searchActive}
                style={{ padding: "2px 6px", fontSize: 12 }}
              >
                <option value="4">4 (엄격)</option>
                <option value="8">8 (기본)</option>
                <option value="12">12 (느슨)</option>
                <option value="16">16 (매우 느슨)</option>
              </select>
            </div>
          </label>
        )}
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

      {loading && items.length === 0 ? (
        <div className="empty">불러오는 중...</div>
      ) : items.length === 0 ? (
        <div className="empty">조건에 맞는 사진이 없습니다.</div>
      ) : (
        <div className="grid">
          {items.map((it) =>
            it.type === "cluster" ? (
              <ClusterCard
                key={`c-${it.cluster_id}`}
                cluster={it}
                onClick={() => setOpenCluster(it)}
              />
            ) : (
              <Card
                key={it.id}
                photo={it}
                isSelected={selected.has(it.id)}
                onToggleSelect={() => toggleSelected(it.id)}
                onClick={() => setOpenPhotoId(it.id)}
              />
            ),
          )}
        </div>
      )}

      {openCluster && (
        <ClusterDetailModal
          cluster={openCluster}
          isSelected={(id) => selected.has(id)}
          onToggleSelect={toggleSelected}
          onOpenPhoto={(id) => {
            setOpenCluster(null);
            setOpenPhotoId(id);
          }}
          onClose={() => setOpenCluster(null)}
        />
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
    // 0-100 → 5단계 색상 빈: 0-19=1, 20-39=2, 40-59=3, 60-79=4, 80-100=5
    const bin = Math.max(1, Math.min(5, Math.floor(displayScore / 20) + 1));
    return `score-${bin}`;
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
          <span style={{ opacity: 0.7, fontSize: "0.85em" }}>/100</span>
        </div>
      )}
      {photo.advanced_review_count && photo.advanced_review_count > 0 ? (
        <div
          title={`고급 평가 ${photo.advanced_review_count}건`}
          style={{
            position: "absolute",
            top: 6,
            right: displayScore !== null && displayScore !== undefined ? 80 : 6,
            background: "rgba(140, 80, 220, 0.92)",
            color: "white",
            padding: "2px 7px",
            borderRadius: 12,
            fontSize: 10,
            fontWeight: 600,
          }}
        >
          고급 {photo.advanced_review_count}
        </div>
      ) : null}
      {photo.documentary_score !== null && photo.documentary_score !== undefined ? (
        <div
          title={`다큐멘터리 점수 ${photo.documentary_score.toFixed(1)} / 100`}
          style={{
            position: "absolute",
            bottom: 36,
            right: 6,
            background: "rgba(40, 100, 60, 0.85)",
            color: "white",
            padding: "1px 6px",
            borderRadius: 10,
            fontSize: 10,
            fontWeight: 600,
          }}
        >
          DOC {photo.documentary_score.toFixed(0)}
        </div>
      ) : null}
      <div className="info">
        <span>{photo.camera_model ?? "-"}</span>
        <span>
          {photo.taken_at ? new Date(photo.taken_at).toLocaleDateString("ko-KR") : "-"}
        </span>
      </div>
    </div>
  );
}

function ClusterCard({
  cluster,
  onClick,
}: {
  cluster: ClusterItem;
  onClick: () => void;
}) {
  const preview = cluster.members[0];
  return (
    <div
      className="card"
      onClick={onClick}
      style={{ position: "relative" }}
      title={`유사 사진 ${cluster.count}장`}
    >
      {/* 스택 효과: 뒤쪽 두 장이 살짝 어긋나 보이도록 */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "var(--panel)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          transform: "translate(6px, 6px)",
          zIndex: 0,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "var(--panel-2)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          transform: "translate(3px, 3px)",
          zIndex: 0,
        }}
      />
      <div style={{ position: "relative", zIndex: 1 }}>
        <img
          src={preview.thumb_url}
          alt={`cluster ${cluster.cluster_id}`}
          className="thumb"
          loading="lazy"
        />
        <div
          style={{
            position: "absolute",
            top: 6,
            left: 6,
            background: "rgba(0,0,0,0.7)",
            color: "white",
            padding: "3px 9px",
            borderRadius: 12,
            fontSize: 11,
            fontWeight: 700,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          ▣ {cluster.count}
        </div>
        <div className="info">
          <span style={{ color: "var(--text-dim)" }}>유사 {cluster.count}장</span>
          <span>
            {preview.taken_at
              ? new Date(preview.taken_at).toLocaleDateString("ko-KR")
              : "-"}
          </span>
        </div>
      </div>
    </div>
  );
}

function ClusterDetailModal({
  cluster,
  isSelected,
  onToggleSelect,
  onOpenPhoto,
  onClose,
}: {
  cluster: ClusterItem;
  isSelected: (id: number) => boolean;
  onToggleSelect: (id: number) => void;
  onOpenPhoto: (id: number) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-bg" onClick={onClose} style={{ zIndex: 90 }}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{
          flexDirection: "column",
          maxWidth: 1000,
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
            유사 사진 그룹 — {cluster.count}장
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
          }}
        >
          <div className="grid" style={{ padding: 0 }}>
            {cluster.members.map((p) => (
              <Card
                key={p.id}
                photo={p}
                isSelected={isSelected(p.id)}
                onToggleSelect={() => onToggleSelect(p.id)}
                onClick={() => onOpenPhoto(p.id)}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
