// Tour state is stored per user id so accounts on the same browser do not affect each other.
// localStorage failures (private mode, blocked storage) must never break the app.

const PREFIX = 'fyp:tour:v1:';
const ACTIVE_PREFIX = 'fyp:tour:active:v1:';
const NEW_ACCOUNT_WINDOW_MS = 24 * 60 * 60 * 1000;

export const readState = (userId) => {
  try {
    return JSON.parse(localStorage.getItem(PREFIX + userId)) || null;
  } catch {
    return null;
  }
};

export const writeState = (userId, status) => {
  try {
    localStorage.setItem(PREFIX + userId, JSON.stringify({ status, at: new Date().toISOString() }));
  } catch {
    /* ignore */
  }
};

export const readActive = (userId) => {
  try {
    const value = sessionStorage.getItem(ACTIVE_PREFIX + userId);
    return value === null ? null : Number(value);
  } catch {
    return null;
  }
};

export const writeActive = (userId, index) => {
  try {
    if (index === null) sessionStorage.removeItem(ACTIVE_PREFIX + userId);
    else sessionStorage.setItem(ACTIVE_PREFIX + userId, String(index));
  } catch {
    /* ignore */
  }
};

// Only accounts created in the last 24 h are offered the tour automatically,
// so existing users are never forced through onboarding (they can still use Help).
export const isNewAccount = (user, now = Date.now()) => {
  const created = user?.created_at ? Date.parse(user.created_at.endsWith('Z') ? user.created_at : `${user.created_at}Z`) : NaN;
  return Number.isFinite(created) && now - created < NEW_ACCOUNT_WINDOW_MS;
};

export const shouldAutoOffer = (user) => Boolean(user?.id) && !readState(user.id) && isNewAccount(user);
