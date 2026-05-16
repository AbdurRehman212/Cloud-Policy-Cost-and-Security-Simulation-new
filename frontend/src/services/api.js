/**
 * Centralized API service — all API calls must use this instance.
 * Backend is served from the same origin as the React build.
 */
import axios from 'axios';
import { io } from 'socket.io-client';

export const API_BASE_URL = '/api';

export const disconnectAllSockets = () => {
  if (!window._socketInstances) return;

  Object.values(window._socketInstances).forEach((socket) => {
    try {
      socket.off();
      socket.disconnect();
    } catch (error) {
      // Best-effort cleanup only.
    }
  });

  window._socketInstances = {};
};

// Shared axios instance with auth token injection
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
});

// Automatically attach JWT token from localStorage
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Log errors globally (no toast here — components handle UX)
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      // Token expired — clear storage but don't redirect here
      localStorage.removeItem('token');
      localStorage.removeItem('refresh_token');
      disconnectAllSockets();
    }
    return Promise.reject(error);
  }
);

export default apiClient;

/**
 * Create a Socket.IO connection to the backend.
 * Use this everywhere instead of direct `io()` calls.
 */
export const createSocket = (namespace = '') => {
  const token = localStorage.getItem('token') || '';
  if (!token) {
    return null;
  }

  // Ensure namespace starts with /
  const ns = namespace && !namespace.startsWith('/') ? `/${namespace}` : namespace;

  // We keep a registry of instances per namespace
  if (!window._socketInstances) window._socketInstances = {};

  if (window._socketInstances[ns]) {
    const existing = window._socketInstances[ns];
    if (existing.connected && existing.auth?.token === token) {
      return existing;
    }
    existing.disconnect();
    delete window._socketInstances[ns];
  }

  const socket = io(ns, {
    transports: ['websocket', 'polling'],
    autoConnect: true,
    auth: {
      token,
    },
    reconnection: true,
    reconnectionAttempts: 10,
    timeout: 20000,
  });

  window._socketInstances[ns] = socket;
  return socket;
};
