import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import axios from "axios";
const API_URL = "http://localhost:5000/api";
export const fetchDashboardSummary = createAsyncThunk(
  "dashboard/fetchSummary",
  async (orgId, { getState, rejectWithValue }) => {
    try {
      const token = getState().auth.token;
      const response = await axios.get(
        `${API_URL}/dashboard/summary?organization_id=${orgId}`,
        { headers: { Authorization: `Bearer ${token}` } },
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
    summary: null,
    loading: false,
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchDashboardSummary.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchDashboardSummary.fulfilled, (state, action) => {
        state.loading = false;
        console.log(action.payload);
        const p = action.payload || {};
        state.summary = {
          ...p,
          security_score: p.security_score ?? p.security?.score ?? 0,
          compliance_score: p.compliance_score ?? p.compliance?.score ?? 0,
          health_score: p.health_score_calculated ?? p.health_score ?? 0,
          monthly_spend: p.costs?.total ?? p.monthly_spend ?? 0,
          total_vms:
            p.total_vms ?? p.resources?.vms?.total ?? p.resources?.total ?? 0,
          running_vms:
            p.running_vms ??
            p.resources?.vms?.running ??
            p.resources?.running ??
            p.running ??
            0,
          running:
            p.running_vms ??
            p.resources?.vms?.running ??
            p.resources?.running ??
            p.running ??
            0,
        };
      })
      .addCase(fetchDashboardSummary.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload || "Failed to fetch dashboard summary";
      });
  },
});
export default dashboardSlice.reducer;
