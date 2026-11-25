"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { get } from "./api";
import { EVENT_KINDS } from "./eventKinds";
import type { Me, Settings } from "./types";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => get<Me>("/auth/me"), staleTime: 60_000 });
/** What this person may change. Viewers read only, so the screens leave out buttons the server would refuse. */
export function usePermissions() {
  const role = useMe().data?.role;
  return { role, canWrite: role === "owner" || role === "approver", isOwner: role === "owner" };
}
export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => get<Settings>("/settings") });

/** Listen to the live event stream. Any event refreshes the numbers on screen, at most once a second.
 *  The stream starts after the newest event that exists now (it would otherwise replay the whole history), every named frame is listened for (the server names
 *  each frame after its kind, and `onmessage` only hears unnamed ones), and a dropped connection is reopened after the last event seen. */
export function useLiveRefresh() {
  const qc = useQueryClient();
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let es: EventSource | null = null;
    let last = 0;
    let stopped = false;
    const refresh = (e: MessageEvent) => {
      const id = Number(e.lastEventId);
      if (Number.isFinite(id) && id > last) last = id;
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      }, 1000);
    };
    const open = () => {
      if (stopped) return;
      es = new EventSource(`/api/events/stream?after=${last}`);
      es.onmessage = refresh;
      for (const kind of EVENT_KINDS) es.addEventListener(kind, refresh as EventListener);
      es.onerror = () => {
        es?.close();
        if (!stopped) retry = setTimeout(open, 3000);
      };
    };
    const start = () => { get<{ id: number }>("/events/latest").then((r) => { last = r.id; open(); }).catch(() => { if (!stopped) retry = setTimeout(start, 3000); }); };
    start();
    return () => {
      stopped = true;
      es?.close();
      if (timer) clearTimeout(timer);
      if (retry) clearTimeout(retry);
    };
  }, [qc]);
}
