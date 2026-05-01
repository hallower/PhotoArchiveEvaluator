import { useEffect, useState } from "react";
import { api, type PhotoDetail } from "../api";

export function PhotoModal({
  photoId,
  onClose,
}: {
  photoId: number;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<PhotoDetail | null>(null);

  useEffect(() => {
    void api.photos.detail(photoId).then(setDetail);
  }, [photoId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="photo-pane">
          {detail ? (
            <img src={`/api/photos/${detail.id}/thumb?size=800`} alt={`photo ${detail.id}`} />
          ) : (
            <div className="empty">불러오는 중...</div>
          )}
        </div>
        <div className="info-pane">
          {detail && (
            <>
              <h3>사진 정보</h3>
              <dl>
                <dt>미학 점수</dt>
                <dd>
                  {detail.evaluations.find((e) => e.model_id !== "clip-prompt")?.ai_score?.toFixed(2) ??
                    "-"}{" "}
                  (raw{" "}
                  {detail.evaluations.find((e) => e.model_id !== "clip-prompt")?.raw_score?.toFixed(2) ??
                    "-"}
                  )
                </dd>
                <dt>prompt 점수</dt>
                <dd>
                  {detail.evaluations.find((e) => e.model_id === "clip-prompt")?.ai_score?.toFixed(2) ??
                    "-"}{" "}
                  (sim{" "}
                  {detail.evaluations.find((e) => e.model_id === "clip-prompt")?.raw_score?.toFixed(3) ??
                    "-"}
                  )
                </dd>
                <dt>촬영일</dt>
                <dd>{detail.taken_at ?? "-"}</dd>
                <dt>카메라</dt>
                <dd>
                  {detail.camera_make} {detail.camera_model}
                </dd>
                <dt>렌즈</dt>
                <dd>{detail.lens_model ?? "-"}</dd>
                <dt>노출</dt>
                <dd>
                  ISO {detail.iso ?? "-"} / f/{detail.aperture ?? "-"} /{" "}
                  {detail.shutter ?? "-"} / {detail.focal_mm ?? "-"}mm
                </dd>
                <dt>크기</dt>
                <dd>
                  {detail.width}×{detail.height} ·{" "}
                  {detail.size_bytes ? Math.round(detail.size_bytes / 1024) : "-"}KB
                </dd>
                {(detail.gps_lat !== null || detail.gps_lon !== null) && (
                  <>
                    <dt>GPS</dt>
                    <dd>
                      {detail.gps_lat?.toFixed(6)}, {detail.gps_lon?.toFixed(6)}
                    </dd>
                  </>
                )}
                <dt>SHA-256</dt>
                <dd style={{ fontSize: 10, color: "var(--text-dim)" }}>
                  {detail.sha256.slice(0, 12)}…
                </dd>
                <dt>경로</dt>
                <dd style={{ fontSize: 10 }}>{detail.paths[0]?.path ?? "-"}</dd>
              </dl>
            </>
          )}
        </div>
        <div className="close" onClick={onClose}>
          ×
        </div>
      </div>
    </div>
  );
}
