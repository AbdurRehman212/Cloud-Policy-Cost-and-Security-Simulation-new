/**
 * Only same-site paths are allowed as post-login redirects. Rejects absolute URLs, protocol-relative
 * targets ("//host"), backslash tricks ("/\host", GHSA-wrjc-x8rr-h8h6) and control characters,
 * which would otherwise turn ?redirect= into an open redirect.
 */
const hasUnsafeCharacter = (value) =>
  Array.from(value).some((ch) => ch === '\\' || ch.charCodeAt(0) < 32 || ch.charCodeAt(0) === 127);

export const safeRedirect = (target, fallback = '/') => {
  if (typeof target !== 'string' || target.length > 512) return fallback;
  if (!target.startsWith('/') || target.startsWith('//') || hasUnsafeCharacter(target)) return fallback;
  try {
    const url = new URL(target, window.location.origin);
    return url.origin === window.location.origin ? `${url.pathname}${url.search}${url.hash}` : fallback;
  } catch (_error) {
    return fallback;
  }
};
