const UNSAFE_IN_SEGMENT = /[?#%\u0000-\u001f\u007f]/;

/** Paths the web app must never forward to the API: sign in goes through /api/session (so the token stays in an httpOnly cookie) and webhooks are for the
 *  senders themselves. The check is made on the path as the API will see it: segments are decoded, dots are resolved and case is ignored when matching, so `./auth/login`,
 *  `%2e/auth/login`, `x/../auth/login` and `Auth/Login` are all refused the same way as `auth/login`. A path that tries to climb out (`..` past the start) or has
 *  an encoded slash or backslash is refused too, and so is a segment that decodes to `?`, `#`, `%` or a control character: those would change where the path
 *  ends once it is joined into a URL (`auth/login%3F` is `auth/login?`, which the API reads as the sign in route with an empty query). */
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
  return out.some((p) => UNSAFE_IN_SEGMENT.test(p)) ? null : out;
}

/** The checked path as it is sent to the API: every segment encoded again, so what was checked is exactly what the API receives. */
export function encodeProxyPath(segments: string[]): string | null {
  const path = normalizeProxyPath(segments);
  return path === null ? null : path.map((p) => encodeURIComponent(p)).join("/");
}

export function isBlockedProxyPath(segments: string[]): boolean {
  const path = normalizeProxyPath(segments);
  if (path === null) return true;
  const [first, second] = path.map((p) => p.toLowerCase());
  return first === "webhooks" || (first === "auth" && second === "login");
}
