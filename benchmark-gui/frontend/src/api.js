import axios from 'axios';
import io from 'socket.io-client';

const configuredBase = (process.env.REACT_APP_API_URL || window.location.origin || '').replace(/\/$/, '');
const configuredApiKey = process.env.REACT_APP_BENCHMARK_API_KEY || '';

export const API_BASE_URL = configuredBase;

export const getApiKey = () => {
  return window.localStorage.getItem('benchmarkApiKey') || configuredApiKey || '';
};

export const setApiKey = (apiKey) => {
  const value = (apiKey || '').trim();
  if (value) {
    window.localStorage.setItem('benchmarkApiKey', value);
  } else {
    window.localStorage.removeItem('benchmarkApiKey');
  }
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
    if (error?.response?.status === 401) {
      notifyAuthError(error.response?.data?.error || error.response?.data?.detail || 'Invalid or missing API key.');
    }
    return Promise.reject(error);
  }
);

export const apiFetch = (path, init = {}) => {
  return fetch(apiUrl(path), {
    ...init,
    headers: {
      ...getAuthHeaders(),
      ...(init.headers || {}),
    },
  }).then(async (response) => {
    if (response.status === 401) {
      let message = 'Invalid or missing API key.';
      try {
        const data = await response.clone().json();
        message = data?.error || data?.detail || message;
      } catch (err) {
        // Ignore parse failures for auth notifications.
      }
      notifyAuthError(message);
    }
    return response;
  });
};

export const createSocketClient = () =>
  io(API_BASE_URL, {
    path: '/socket.io',
    transports: ['websocket', 'polling'],
    auth: {
      apiKey: getApiKey(),
    },
  });
