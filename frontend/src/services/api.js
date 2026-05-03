/**
 * Centralized API service — all API calls must use this instance.
 * Backend is served from the same origin as the React build.
 */
import axios from 'axios';
import { io } from 'socket.io-client';

export const API_BASE_URL = '/api';

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
    }
    return Promise.reject(error);
  }
);

export default apiClient;

/**
 * Create a Socket.IO connection to the backend.
 * Use this everywhere instead of direct `io()` calls.
 */
let socketInstance = null;

export const createSocket = () => {
  const token = localStorage.getItem('token') || '';
  if (!token) {
    return null;
  }

  if (socketInstance) {
    const currentToken = socketInstance.auth?.token || '';
    if (currentToken === token && socketInstance.connected) {
      return socketInstance;
    }

    socketInstance.disconnect();
    socketInstance.close();
    socketInstance = null;
  }

  socketInstance = io({
    transports: ['polling'],
    autoConnect: false,
    auth: {
      token,
    },
    reconnection: false,
    timeout: 10000,
  });
  socketInstance.connect();
  return socketInstance;
};
