import { useEffect, useRef, useState } from "react";
import { apiUrl } from "@/api";

export type PipelineProgress = {
  visible: boolean;
  encoding: boolean;
  percent: number;
  title: string;
  detail: string;
  task_id: number | null;
  queue_total: number;
  queue_done: number;
  fps: number;
  speed: number;
  eta_sec: number;
};

const EMPTY: PipelineProgress = {
  visible: false,
  encoding: false,
  percent: 0,
  title: "",
  detail: "",
  task_id: null,
  queue_total: 0,
  queue_done: 0,
  fps: 0,
  speed: 0,
  eta_sec: 0,
};

export function usePipelineSSE(tenantId: string): PipelineProgress {
  const [progress, setProgress] = useState<PipelineProgress>(EMPTY);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const url = apiUrl(
      `/api/pipeline/events?tenant_id=${encodeURIComponent(tenantId)}`,
    );
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data as string) as Partial<PipelineProgress>;
        if (data && typeof data === "object" && Object.keys(data).length > 0) {
          setProgress((prev) => ({ ...prev, ...data }));
        }
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      // SSE auto-reconnects; reset visible state so UI doesn't show stale progress
      setProgress(EMPTY);
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [tenantId]);

  return progress;
}
