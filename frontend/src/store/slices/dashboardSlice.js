import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import apiClient from "../../services/api";
import { setCurrentOrganization, switchOrganization } from "./organizationSlice";

const hasSnapshotBody = (payload) => (
  payload
  && typeof payload === "object"
  && (
    payload.resources
    || payload.costs
    || payload.security
    || payload.utilization_trend
    || payload.cost_trend
    || payload.workload
    || payload.capacity !== undefined
    || payload.bpi !== undefined
    || payload.target_bpi !== undefined
  )
);

export const normalizeDashboardSnapshot = (payload, activeOrgId = null) => {
  if (!hasSnapshotBody(payload)) {
    return null;
  }

  const orgId = payload.org_id ?? payload.organization_id ?? activeOrgId ?? null;
  if (activeOrgId !== null && orgId !== null && orgId !== activeOrgId) {
    return null;
  }
  if (orgId === null) {
    return null;
  }

  return {
    ...payload,
    org_id: orgId,
    organization_id: payload.organization_id ?? orgId,
  };
};

const getOrgId = (value) => {
  if (value && typeof value === "object") {
    return value.orgId ?? value.organization_id ?? value.org_id ?? null;
  }
  return value ?? null;
};
export const fetchDashboardSummary = createAsyncThunk(
  "dashboard/fetchSummary",
  async (orgId, { getState, rejectWithValue }) => {
    try {
      const response = await apiClient.get(
        `/dashboard/summary?organization_id=${orgId}`,
      );
      return response.data;
    } catch (error) {
      return rejectWithValue(error.response?.data?.error);
    }
  },
);
const dashboardSlice = createSlice({
  name: "dashboard",
  initialState: {
    activeOrgId: null,
    summary: null,
    loading: false,
    error: null,
  },
  reducers: {
    updateDashboardState: (state, action) => {
      const normalized = normalizeDashboardSnapshot(action.payload, state.activeOrgId);
      if (!normalized) return;
      state.summary = normalized;
    },
    clearDashboard: (state) => {
      state.activeOrgId = null;
      state.summary = null;
      state.loading = false;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(setCurrentOrganization, (state, action) => {
        state.activeOrgId = action.payload?.id ?? null;
        state.summary = null;
        state.loading = false;
        state.error = null;
      })
      .addCase(switchOrganization, (state, action) => {
        state.activeOrgId = action.payload?.id ?? null;
        state.summary = null;
        state.loading = false;
        state.error = null;
      })
      .addCase(fetchDashboardSummary.pending, (state, action) => {
        state.loading = true;
        state.error = null;
        state.activeOrgId = getOrgId(action.meta.arg);
      })
      .addCase(fetchDashboardSummary.fulfilled, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.loading = false;
        const normalized = normalizeDashboardSnapshot(action.payload, state.activeOrgId);
        state.summary = normalized || null;
      })
      .addCase(fetchDashboardSummary.rejected, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.loading = false;
        state.error = action.payload || "Failed to fetch dashboard summary";
      });
  },
});
export const { updateDashboardState, clearDashboard } = dashboardSlice.actions;
export default dashboardSlice.reducer;
