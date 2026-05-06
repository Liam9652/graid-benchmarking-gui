import axios from 'axios';
import io from 'socket.io-client';

const configuredBase = (process.env.REACT_APP_API_URL || window.location.origin || '').replace(/\/$/, '');

export const API_BASE_URL = configuredBase;

// Single source of truth for the API key. setApiKey writes to localStorage
// AND dispatches `benchmark-api-key-change` so React (via useSyncExternalStore
// in App.jsx) and any future subscribers stay in sync (FE-5/FE-8 in AUDIT.md).
const API_KEY_STORAGE = 'benchmarkApiKey';
const API_KEY_EVENT = 'benchmark-api-key-change';

export const getApiKey = () => {
  return window.localStorage.getItem(API_KEY_STORAGE) || '';
};

export const setApiKey = (apiKey) => {
  const value = (apiKey || '').trim();
  const previous = getApiKey();
  if (value) {
    window.localStorage.setItem(API_KEY_STORAGE, value);
  } else {
    window.localStorage.removeItem(API_KEY_STORAGE);
  }
  if (value !== previous) {
    window.dispatchEvent(new CustomEvent(API_KEY_EVENT, { detail: { value } }));
  }
};

// Subscribe callback fires whenever setApiKey() changes the stored value,
// or when another tab writes to the same localStorage key. Returns an
// unsubscribe function suitable for useSyncExternalStore / useEffect cleanup.
export const subscribeApiKey = (callback) => {
  const onCustom = () => callback();
  const onStorage = (event) => {
    if (event.key === API_KEY_STORAGE) callback();
  };
  window.addEventListener(API_KEY_EVENT, onCustom);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(API_KEY_EVENT, onCustom);
    window.removeEventListener('storage', onStorage);
  };
};

export const getAuthHeaders = () => {
  const apiKey = getApiKey();
  return apiKey ? { 'X-API-Key': apiKey } : {};
};

export const apiUrl = (path) => `${API_BASE_URL}${path}`;

export const apiClient = axios.create();

const notifyAuthError = (message) => {
  window.dispatchEvent(new CustomEvent('benchmark-auth-error', {
    detail: {
      message: message || 'Protected action failed. Check the API key and try again.',
    },
  }));
};

const isApiKeyAuthError = (response, payload) => {
  // The backend returns 401 for two distinct reasons:
  //   1. Missing/invalid X-API-Key header (require_api_key)
  //   2. Expired or invalid SSH session token (restore_session)
  // Only #1 should trigger the global "🔐 reconfigure your API key" UX.
  // Prefer an explicit code field; fall back to header inspection; finally
  // fall back to a message-text heuristic so older backends stay supported.
  const code = payload?.code || payload?.data?.code;
  if (code === 'invalid_api_key' || code === 'missing_api_key') return true;
  if (code === 'session_expired' || code === 'session_invalid') return false;
  const wwwAuth = response?.headers?.get?.('www-authenticate');
  if (wwwAuth && /api[-_]?key/i.test(wwwAuth)) return true;
  const message = payload?.error || payload?.detail || '';
  if (/session/i.test(message)) return false;
  // Default to treating unknown 401s as API-key failures since that is the
  // historical behavior callers depend on.
  return true;
};

apiClient.interceptors.request.use((config) => {
  config.headers = {
    ...(config.headers || {}),
    ...getAuthHeaders(),
  };
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const config = error?.config || {};
    const skipAuthHandler = Boolean(config.skipAuthErrorHandler);
    if (!skipAuthHandler && error?.response?.status === 401) {
      const payload = error.response?.data;
      if (isApiKeyAuthError(error.response, payload)) {
        notifyAuthError(payload?.error || payload?.detail || 'Invalid or missing API key.');
      }
    }
    return Promise.reject(error);
  }
);

export const apiFetch = (path, init = {}) => {
  const { skipAuthErrorHandler, ...fetchInit } = init;
  return fetch(apiUrl(path), {
    ...fetchInit,
    headers: {
      ...getAuthHeaders(),
      ...(fetchInit.headers || {}),
    },
  }).then(async (response) => {
    if (!skipAuthErrorHandler && response.status === 401) {
      let payload = null;
      try {
        payload = await response.clone().json();
      } catch (err) {
        // Ignore parse failures — fall through to default messaging.
      }
      if (isApiKeyAuthError(response, payload)) {
        notifyAuthError(payload?.error || payload?.detail || 'Invalid or missing API key.');
      }
    }
    return response;
  });
};

// Returns null when no API key is configured. Callers should handle null and
// only call createSocketClient() once a key is available; otherwise the server
// rejects the handshake and socket.io-client retries forever, drowning the UI
// in connect_error toasts before the user has a chance to enter the key.
export const createSocketClient = () => {
  const apiKey = getApiKey();
  if (!apiKey) return null;
  return io(API_BASE_URL, {
    path: '/socket.io',
    transports: ['websocket', 'polling'],
    auth: {
      apiKey,
    },
    // Cap reconnect attempts so a transient backend restart doesn't produce
    // an unbounded stream of error toasts; users can refresh to retry.
    reconnectionAttempts: 5,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
  });
};
