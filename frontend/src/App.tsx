import { useEffect, useState } from "react";
import { api, ApiError, type AuthStatus } from "./api";
import { LoginPage } from "./pages/LoginPage";
import { LibraryPage } from "./pages/LibraryPage";

export default function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.auth
      .status()
      .then(setAuthStatus)
      .catch((e: ApiError) => setError(e.detail || e.message));
  }, []);

  if (error) {
    return <div className="empty">백엔드 연결 실패: {error}</div>;
  }
  if (!authStatus) {
    return <div className="empty">로딩 중...</div>;
  }

  if (!authStatus.authenticated) {
    return (
      <LoginPage
        setupRequired={authStatus.setup_required}
        onSuccess={() => api.auth.status().then(setAuthStatus)}
      />
    );
  }

  return (
    <LibraryPage
      onLogout={async () => {
        await api.auth.logout();
        setAuthStatus(await api.auth.status());
      }}
    />
  );
}
