import { useEffect, useState } from "react";
import { api } from "../api";

export function PromptDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [defaultPrompt, setDefaultPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.eval.getPrompt().then((r) => {
      setPrompt(r.prompt);
      setDefaultPrompt(r.default);
    });
  }, []);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.eval.putPrompt(prompt);
      // 임베딩은 그대로, prompt 점수만 재계산 (CLIP forward 불필요, 빠름)
      await api.eval.rescorePrompt();
      onSaved();
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
        style={{ maxWidth: 640, flexDirection: "column", padding: 20 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: "0 0 12px 0" }}>평가 prompt</h3>
        <p style={{ color: "var(--text-dim)", fontSize: 12, margin: "0 0 12px 0" }}>
          CLIP이 이 prompt와 사진을 비교해 1–5점을 부여합니다. 영어로 쓰는 게
          정확합니다. 저장 시 기존 임베딩만 재사용해 즉시 재평가됩니다.
        </p>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={5}
          style={{
            background: "var(--panel-2)",
            color: "var(--text)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: 10,
            font: "inherit",
            resize: "vertical",
          }}
        />
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 12,
          }}
        >
          <button
            className="ghost"
            onClick={() => setPrompt(defaultPrompt)}
            disabled={busy}
            type="button"
          >
            기본값으로 복원
          </button>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="ghost" onClick={onClose} disabled={busy}>
              취소
            </button>
            <button onClick={save} disabled={busy || !prompt.trim()}>
              {busy ? "재평가 중..." : "저장 + 재평가"}
            </button>
          </div>
        </div>
        {error && (
          <div style={{ color: "var(--danger)", marginTop: 10, fontSize: 13 }}>
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
