/** Paths the web app must never forward to the API: sign in goes through /api/session (so the token stays in an httpOnly cookie) and webhooks are for the
 *  senders themselves. The check is made on the path as the API will see it: segments are decoded, dots are resolved and case is ignored when matching, so `./auth/login`,
 *  `%2e/auth/login`, `x/../auth/login` and `Auth/Login` are all refused the same way as `auth/login`. A path that tries to climb out (`..` past the start) or has
 *  an encoded slash or backslash is refused too. */
export function normalizeProxyPath(segments: string[]): string[] | null {
  const out: string[] = [];
  for (const raw of segments) {
    let part: string;
    try { part = decodeURIComponent(raw); } catch { return null; }
    for (const piece of part.split(/[\\/]/)) {
      if (piece === "" || piece === ".") continue;
      if (piece === "..") { if (!out.length) return null; out.pop(); continue; }
      out.push(piece);
    }
    if (/[\\]/.test(part)) return null;
  }
  return out;
}

export function isBlockedProxyPath(segments: string[]): boolean {
  const path = normalizeProxyPath(segments);
  if (path === null) return true;
  const [first, second] = path.map((p) => p.toLowerCase());
  return first === "webhooks" || (first === "auth" && second === "login");
}
