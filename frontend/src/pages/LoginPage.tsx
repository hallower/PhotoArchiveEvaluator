import { useState } from "react";
import { api, ApiError } from "../api";

export function LoginPage({
  setupRequired,
  onSuccess,
}: {
  setupRequired: boolean;
  onSuccess: () => void;
}) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (setupRequired) {
        if (password.length < 8) {
          setError("8자 이상 입력해 주세요.");
          return;
        }
        await api.auth.setup(password);
      } else {
        await api.auth.login(password);
      }
      onSuccess();
    } catch (e) {
      const msg = e instanceof ApiError ? e.detail || e.message : String(e);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="center-panel" onSubmit={submit}>
      <h2>{setupRequired ? "초기 비밀번호 설정" : "로그인"}</h2>
      <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: -8 }}>
        {setupRequired
          ? "처음 사용 시 8자 이상 비밀번호를 설정합니다. 이후 로그인에 사용됩니다."
          : "Photo Archive Evaluator"}
      </p>
      <div className="form-row">
        <label>비밀번호</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
          autoComplete={setupRequired ? "new-password" : "current-password"}
        />
      </div>
      <div className="actions">
        <button type="submit" disabled={busy || !password}>
          {busy ? "처리 중..." : setupRequired ? "설정" : "로그인"}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
    </form>
  );
}
