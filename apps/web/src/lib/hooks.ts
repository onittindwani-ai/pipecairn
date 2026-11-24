"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { get } from "./api";
import type { Me, Settings } from "./types";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => get<Me>("/auth/me"), staleTime: 60_000 });
/** What this person may change. Viewers read only, so the screens leave out buttons the server would refuse. */
export function usePermissions() {
  const role = useMe().data?.role;
  return { role, canWrite: role === "owner" || role === "approver", isOwner: role === "owner" };
}
export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => get<Settings>("/settings") });

/** Listen to the live event stream. Any event refreshes the numbers on screen, at most once a second. */
export function useLiveRefresh() {
  const qc = useQueryClient();
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const es = new EventSource("/api/events/stream");
    es.onmessage = () => {
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      }, 1000);
    };
    return () => {
      es.close();
      if (timer) clearTimeout(timer);
    };
  }, [qc]);
}
