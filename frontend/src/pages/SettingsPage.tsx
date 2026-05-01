import { useEffect, useState } from "react";
import { api, type AppSettings, type BackupRecord } from "../api";

export function SettingsPage({ onClose }: { onClose: () => void }) {
  const [s, setS] = useState<AppSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [backups, setBackups] = useState<BackupRecord[]>([]);

  useEffect(() => {
    void api.settings.get().then(setS);
    void api.backup.list().then(setBackups).catch(() => {});
  }, []);

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
