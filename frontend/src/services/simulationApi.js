import axios from 'axios';
import { io } from 'socket.io-client';

// Legacy compatibility API.
// The real dashboard now reads from /api/dashboard/summary and the control-plane
// snapshot cache; keep this module only for older callers that have not been removed yet.

const apiClient = axios.create({
  baseURL: process.env.REACT_APP_API_URL || '/api',
});

const SOCKET_URL = process.env.REACT_APP_SOCKET_URL;

const unwrapResponse = (response) => {
  const payload = response.data;
  if (payload?.status === 'success') {
    return payload.data;
  }
  return payload;
};

const buildSimulationParams = ({ points = 30, seed } = {}) => ({
  points,
  seed,
});

export const fetchMetrics = async (params = {}) => {
  const response = await apiClient.get('/metrics', { params: buildSimulationParams(params) });
  return unwrapResponse(response);
};

export const fetchSummary = async () => {
  const response = await apiClient.get('/summary');
  return unwrapResponse(response);
};

export const fetchPeaks = async () => {
  const response = await apiClient.get('/peaks');
  return unwrapResponse(response);
};

export const fetchCost = async (params = {}) => {
  const response = await apiClient.get('/cost', { params: buildSimulationParams(params) });
  return unwrapResponse(response);
};

export const fetchSimulationDashboard = async (points = 30) => {
  const seed = Date.now() % 4294967295;
  const [metrics, summary, peaks, cost] = await Promise.all([
    fetchMetrics({ points, seed }),
    fetchSummary(),
    fetchPeaks(),
    fetchCost({ points, seed }),
  ]);

  return {
    metrics,
    summary,
    peaks,
    cost,
  };
};

export const fetchSimulationStats = async (points = 30) => {
  const seed = Date.now() % 4294967295;
  const [summary, peaks, cost] = await Promise.all([
    fetchSummary(),
    fetchPeaks(),
    fetchCost({ points, seed }),
  ]);

  return {
    summary,
    peaks,
    cost,
  };
};

export const createMetricsSocket = () =>
  io(SOCKET_URL, {
    transports: ['polling', 'websocket'],
    reconnection: true,
    reconnectionAttempts: 10,
    reconnectionDelay: 1000,
  });
