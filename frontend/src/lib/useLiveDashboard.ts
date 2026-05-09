// useLiveDashboard — WebSocket hook for the Dashboard live overview.
//
// Contract:
//   - Returns { data, status, lastSeenAt } reactive state.
//   - Opens /api/v1/ws/dashboard via cookie auth (same-origin).
//   - On disconnect: exponential backoff up to 30 s, then keep retrying.
//   - Falls open: a consumer can also keep its REST polling so the UI
//     never goes blank if the WS breaks. The hook just exposes status.

import { useEffect, useRef, useState } from "react";
import type { MetricsOverview } from "./types";

export interface LiveOverview extends MetricsOverview {
  generated_at: string;
  fallback?: boolean;
}

export type LiveStatus = "idle" | "connecting" | "open" | "closed" | "error";

interface UseLiveDashboardResult {
  data: LiveOverview | null;
  status: LiveStatus;
  /** Wall-clock timestamp of the last received frame (ms). */
  lastSeenAt: number | null;
}

const WS_PATH = "/api/v1/ws/dashboard";
const MAX_BACKOFF_MS = 30_000;

function wsUrl(): string {
  // Same origin as the SPA; nginx proxies /api/ to the backend with
  // upgrade headers. Browser cookies attach automatically.
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${WS_PATH}`;
}

export function useLiveDashboard(enabled = true): UseLiveDashboardResult {
  const [data, setData] = useState<LiveOverview | null>(null);
  const [status, setStatus] = useState<LiveStatus>("idle");
  const [lastSeenAt, setLastSeenAt] = useState<number | null>(null);

  // We keep the socket + reconnect timer in refs so re-renders don't
  // recreate them. The effect is a tight close-over of these refs.
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffRef = useRef<number>(500);
  const aliveRef = useRef<boolean>(true);

  useEffect(() => {
    aliveRef.current = true;

    function connect(): void {
      if (!aliveRef.current || !enabled) return;
      setStatus("connecting");
      const sock = new WebSocket(wsUrl());
      socketRef.current = sock;

      sock.addEventListener("open", () => {
        if (!aliveRef.current) return;
        setStatus("open");
        backoffRef.current = 500;  // reset on successful open
      });

      sock.addEventListener("message", (ev) => {
        if (!aliveRef.current) return;
        try {
          const parsed = JSON.parse(ev.data) as LiveOverview;
          setData(parsed);
          setLastSeenAt(Date.now());
        } catch {
          // Server sends only JSON; a parse failure is the server's
          // bug, not ours. We log and ignore so the UI stays alive.
          // eslint-disable-next-line no-console
          console.warn("[live-dashboard] invalid frame", ev.data);
        }
      });

      sock.addEventListener("error", () => {
        if (!aliveRef.current) return;
        setStatus("error");
        // 'close' fires after 'error', so the reconnect schedule is
        // handled there.
      });

      sock.addEventListener("close", () => {
        if (!aliveRef.current) return;
        setStatus("closed");
        // Exponential backoff with cap. 1.6× factor keeps the schedule
        // gentle on a flapping ml-service.
        const delay = Math.min(backoffRef.current, MAX_BACKOFF_MS);
        backoffRef.current = Math.min(
          MAX_BACKOFF_MS,
          Math.round(backoffRef.current * 1.6),
        );
        retryRef.current = setTimeout(connect, delay);
      });
    }

    if (enabled) connect();

    return () => {
      aliveRef.current = false;
      if (retryRef.current) clearTimeout(retryRef.current);
      if (socketRef.current && socketRef.current.readyState <= WebSocket.OPEN) {
        socketRef.current.close();
      }
    };
  }, [enabled]);

  return { data, status, lastSeenAt };
}
