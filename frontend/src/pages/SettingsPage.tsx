import { useEffect, useState } from "react";
import { api, type AppSettings, type BackupRecord, type ScanJob } from "../api";

export function SettingsPage({ onClose }: { onClose: () => void }) {
  const [s, setS] = useState<AppSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [backups, setBackups] = useState<BackupRecord[]>([]);
  const [failedJobs, setFailedJobs] = useState<ScanJob[]>([]);

  const loadFailed = () =>
    api.scan
      .jobs({ state: "failed", limit: 50 })
      .then(setFailedJobs)
      .catch(() => {});

  useEffect(() => {
    void api.settings.get().then(setS);
    void api.backup.list().then(setBackups).catch(() => {});
    void loadFailed();
  }, []);

  const retryAllFailed = async () => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const r = await api.scan.retryFailed();
      setInfo(`${r.retried_jobs}개 잡에 대해 ${r.started_scans}개 스캔이 시작됨`);
      setTimeout(loadFailed, 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const retryOne = async (id: number) => {
    setBusy(true);
    try {
      await api.scan.retryJob(id);
      setTimeout(loadFailed, 2000);
    } finally {
      setBusy(false);
    }
  };

  const deleteOne = async (id: number) => {
    setBusy(true);
    try {
      await api.scan.deleteJob(id);
      void loadFailed();
    } finally {
      setBusy(false);
    }
  };

  const deleteAllFailed = async () => {
    if (!window.confirm(`${failedJobs.length}개 실패 잡을 모두 삭제할까요?`)) return;
    setBusy(true);
    try {
      const r = await api.scan.bulkDeleteJobs("failed");
      setInfo(`${r.deleted}개 삭제됨`);
      void loadFailed();
    } finally {
      setBusy(false);
    }
  };

  const triggerBackup = async () => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await api.backup.trigger();
      setInfo("백업이 백그라운드로 시작됨. 잠시 후 목록 새로고침.");
      setTimeout(() => {
        void api.backup.list().then(setBackups);
      }, 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!s) {
    return (
      <div className="modal-bg" onClick={onClose}>
        <div className="empty">로딩 중...</div>
      </div>
    );
  }

  const update = (patch: Partial<AppSettings>) => setS({ ...s, ...patch });

  const save = async () => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const r = await api.settings.put({
        eval_prompt: s.eval_prompt,
        library_min_score: s.library_min_score,
        scan_local_paths: s.scan_local_paths,
        scan_dsm_paths: s.scan_dsm_paths,
        eval_max_workers: s.eval_max_workers,
      });
      setInfo(
        r.prompt_rescored
          ? "저장됨. prompt 변경 → 백그라운드 재평가 중"
          : "저장됨",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const scanAll = async () => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const r = await api.settings.scanSaved();
      setInfo(
        `스캔 시작됨 — 로컬 ${r.started.local}개, NAS ${r.started.dsm}개`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <div
        className="modal"
        style={{
          maxWidth: 720,
          flexDirection: "column",
          padding: 24,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ margin: "0 0 16px 0", fontSize: 18 }}>설정</h2>

        <Section title="라이브러리">
          <label style={{ color: "var(--text-dim)", fontSize: 12 }}>
            기본 표시 임계값 (라이브러리 첫 진입 시)
          </label>
          <input
            type="number"
            min={0}
            max={5}
            step={0.1}
            value={s.library_min_score}
            onChange={(e) =>
              update({ library_min_score: parseFloat(e.target.value) || 0 })
            }
            style={{ width: 120 }}
          />
        </Section>

        <Section title="동시 평가 워커 수">
          <p style={{ color: "var(--text-dim)", fontSize: 12, margin: "0 0 8px 0" }}>
            평가 큐를 처리하는 백그라운드 워커 수. 단일 GPU에서 NAS 다운로드와 GPU 추론을
            오버랩하기 위함이며, 2가 sweet spot입니다 (단일 GPU + I/O 병렬).
            너무 크면 VRAM/메모리 압박, 너무 작으면 다운로드 대기로 GPU가 놉니다.
            <br />
            <strong>변경 후 서버 재시작</strong>이 필요합니다 (현재 워커는 그대로 동작).
          </p>
          <input
            type="number"
            min={1}
            max={s.max_allowed_workers}
            value={s.eval_max_workers}
            onChange={(e) =>
              update({ eval_max_workers: parseInt(e.target.value, 10) || 1 })
            }
            style={{ width: 120 }}
          />
          <span style={{ color: "var(--text-dim)", fontSize: 11, marginLeft: 8 }}>
            기본 {s.default_eval_max_workers} / 최대 {s.max_allowed_workers}
          </span>
        </Section>

        <Section title="평가 prompt">
          <p style={{ color: "var(--text-dim)", fontSize: 12, margin: "0 0 8px 0" }}>
            CLIP이 이 prompt와 사진을 비교해 1–5점을 부여합니다. 영어로 쓰는 게
            정확합니다. 저장 시 기존 임베딩으로 즉시 재평가됩니다.
          </p>
          <textarea
            value={s.eval_prompt}
            onChange={(e) => update({ eval_prompt: e.target.value })}
            rows={4}
            style={textareaStyle}
          />
          <button
            type="button"
            className="ghost"
            style={{ marginTop: 6, alignSelf: "flex-start" }}
            onClick={() => update({ eval_prompt: s.default_eval_prompt })}
          >
            기본값으로 복원
          </button>
        </Section>

        <Section title="로컬 스캔 폴더">
          <PathList
            paths={s.scan_local_paths}
            onChange={(scan_local_paths) => update({ scan_local_paths })}
            placeholder='Windows 절대경로 (예: C:\Users\you\Pictures\folder)'
          />
        </Section>

        <Section title="NAS (DSM) 스캔 폴더">
          <PathList
            paths={s.scan_dsm_paths}
            onChange={(scan_dsm_paths) => update({ scan_dsm_paths })}
            placeholder='DSM 절대경로 (예: /photo/My Pictures-2023)'
          />
        </Section>

        <Section title={`실패한 스캔 (${failedJobs.length})`}>
          <p style={{ color: "var(--text-dim)", fontSize: 12, margin: "0 0 8px 0" }}>
            서버는 30분마다 실패한 스캔을 자동 재시도합니다. 즉시 재시도하려면 아래 버튼.
          </p>
          <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <button onClick={retryAllFailed} disabled={busy || failedJobs.length === 0}>
              모두 재시도
            </button>
            <button
              className="ghost"
              onClick={deleteAllFailed}
              disabled={busy || failedJobs.length === 0}
              style={{ color: "var(--danger)" }}
            >
              모두 삭제
            </button>
          </div>
          {failedJobs.length === 0 ? (
            <div style={{ color: "var(--text-dim)", fontSize: 12 }}>실패한 스캔 없음</div>
          ) : (
            <div style={{ fontSize: 11, display: "flex", flexDirection: "column", gap: 4 }}>
              {failedJobs.map((j) => (
                <div
                  key={j.id}
                  style={{
                    display: "flex",
                    gap: 6,
                    padding: "6px 8px",
                    background: "var(--panel)",
                    borderRadius: 4,
                    alignItems: "center",
                  }}
                >
                  <span style={{ width: 30, color: "var(--text-dim)" }}>#{j.id}</span>
                  <span style={{ width: 90 }}>
                    {j.started_at ? new Date(j.started_at).toLocaleString("ko-KR") : "-"}
                  </span>
                  <span style={{ flex: 1, wordBreak: "break-all", color: "var(--danger)" }}>
                    {j.error ?? ""}
                  </span>
                  <button
                    className="ghost"
                    onClick={() => retryOne(j.id)}
                    disabled={busy}
                    style={{ padding: "2px 8px", fontSize: 10 }}
                  >
                    재시도
                  </button>
                  <button
                    className="ghost"
                    onClick={() => deleteOne(j.id)}
                    disabled={busy}
                    style={{ padding: "2px 8px", fontSize: 10, color: "var(--danger)" }}
                  >
                    삭제
                  </button>
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section title="외부 API (고급 평가)">
          <p style={{ color: "var(--text-dim)", fontSize: 12, margin: "0 0 10px 0" }}>
            Claude vision 등 외부 비전 모델로 사진별 자연어 리뷰. 사진 데이터가
            네트워크 외부로 전송됩니다.
          </p>

          <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
            <input
              type="checkbox"
              checked={s.external_allow_send}
              onChange={(e) => update({ external_allow_send: e.target.checked })}
            />
            <span style={{ fontSize: 13 }}>외부 전송 허용 (체크 안 하면 호출 차단)</span>
          </label>
          <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
            <input
              type="checkbox"
              checked={s.external_strip_exif}
              onChange={(e) => update({ external_strip_exif: e.target.checked })}
            />
            <span style={{ fontSize: 13 }}>전송 전 EXIF·GPS 제거 (권장 ON)</span>
          </label>

          <div style={{ marginBottom: 10, fontSize: 12 }}>
            <label style={{ display: "block", color: "var(--text-dim)", marginBottom: 4 }}>
              기본 모델
            </label>
            <select
              value={s.external_default_model}
              onChange={(e) => update({ external_default_model: e.target.value })}
            >
              <option value="claude-haiku-4-5">claude-haiku-4-5 (저렴)</option>
              <option value="claude-sonnet-4-6">claude-sonnet-4-6 (균형)</option>
              <option value="claude-opus-4-7">claude-opus-4-7 (최고)</option>
            </select>
          </div>

          <ApiKeyEditor
            provider="anthropic"
            label="Anthropic API 키"
            isSet={s.configured_api_providers.includes("anthropic")}
            onChange={() =>
              api.settings.get().then(setS)
            }
          />
        </Section>

        <Section title="DB 백업">
          <p style={{ color: "var(--text-dim)", fontSize: 12, margin: "0 0 8px 0" }}>
            현재 SQLite DB를 NAS의 <code>/photo/.photoarchive/backups/</code> 폴더로 즉시 복사합니다.
            NAS 미설정 시 로컬 <code>data/backups/</code>로 fallback. 사진 원본은 백업 대상이 아닙니다.
          </p>
          <button onClick={triggerBackup} disabled={busy} style={{ alignSelf: "flex-start" }}>
            지금 백업
          </button>
          {backups.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-dim)" }}>
              {backups.slice(0, 5).map((b) => (
                <div key={b.id} style={{ display: "flex", gap: 8, padding: "3px 0" }}>
                  <span style={{ width: 30 }}>#{b.id}</span>
                  <span
                    style={{
                      width: 60,
                      color:
                        b.state === "done"
                          ? "var(--score-4)"
                          : b.state === "failed"
                          ? "var(--danger)"
                          : "var(--text-dim)",
                    }}
                  >
                    {b.state}
                  </span>
                  <span style={{ width: 80 }}>
                    {b.size_bytes ? `${Math.round(b.size_bytes / 1024)}KB` : "-"}
                  </span>
                  <span style={{ width: 60 }}>{b.photo_count ?? "-"}장</span>
                  <span style={{ flex: 1, wordBreak: "break-all" }}>
                    {b.nas_path ?? b.error ?? ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Section>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 16,
            gap: 10,
          }}
        >
          <button className="ghost" onClick={scanAll} disabled={busy}>
            저장된 폴더 모두 스캔
          </button>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="ghost" onClick={onClose} disabled={busy}>
              닫기
            </button>
            <button onClick={save} disabled={busy}>
              {busy ? "저장 중..." : "저장"}
            </button>
          </div>
        </div>
        {info && (
          <div style={{ color: "var(--score-4)", marginTop: 10, fontSize: 13 }}>
            {info}
          </div>
        )}
        {error && (
          <div style={{ color: "var(--danger)", marginTop: 10, fontSize: 13 }}>
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section
      style={{
        background: "var(--panel-2)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: 14,
        marginBottom: 12,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{title}</h3>
      {children}
    </section>
  );
}

function ApiKeyEditor({
  provider,
  label,
  isSet,
  onChange,
}: {
  provider: string;
  label: string;
  isSet: boolean;
  onChange: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!draft.trim()) return;
    setBusy(true);
    try {
      await api.settings.putApiKey(provider, draft.trim());
      setDraft("");
      onChange();
    } finally {
      setBusy(false);
    }
  };
  const clear = async () => {
    if (!window.confirm(`${provider} 키를 키체인에서 제거할까요?`)) return;
    setBusy(true);
    try {
      await api.settings.deleteApiKey(provider);
      onChange();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <label style={{ display: "block", color: "var(--text-dim)", fontSize: 12, marginBottom: 4 }}>
        {label} {isSet && <span style={{ color: "var(--score-4)" }}>● 등록됨 (키체인)</span>}
      </label>
      <div style={{ display: "flex", gap: 6 }}>
        <input
          type="password"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={isSet ? "(저장됨 — 새 키로 교체하려면 입력)" : "sk-ant-..."}
          style={{ flex: 1 }}
          autoComplete="off"
        />
        <button onClick={save} disabled={busy || !draft.trim()}>저장</button>
        {isSet && (
          <button className="ghost" onClick={clear} disabled={busy} style={{ color: "var(--danger)" }}>
            제거
          </button>
        )}
      </div>
    </div>
  );
}

function PathList({
  paths,
  onChange,
  placeholder,
}: {
  paths: string[];
  onChange: (paths: string[]) => void;
  placeholder: string;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const t = draft.trim();
    if (!t) return;
    if (paths.includes(t)) {
      setDraft("");
      return;
    }
    onChange([...paths, t]);
    setDraft("");
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {paths.length === 0 && (
        <div style={{ color: "var(--text-dim)", fontSize: 12 }}>등록된 폴더 없음</div>
      )}
      {paths.map((p, i) => (
        <div
          key={`${p}-${i}`}
          style={{
            display: "flex",
            gap: 6,
            alignItems: "center",
            background: "var(--panel)",
            borderRadius: 6,
            padding: "6px 10px",
            fontSize: 12,
          }}
        >
          <span style={{ flex: 1, wordBreak: "break-all" }}>{p}</span>
          <button
            className="ghost"
            type="button"
            onClick={() => onChange(paths.filter((_, j) => j !== i))}
            style={{ padding: "4px 10px", fontSize: 11 }}
          >
            제거
          </button>
        </div>
      ))}
      <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          style={{ flex: 1 }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" onClick={add}>
          추가
        </button>
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
