import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import apiClient from "../../services/api";
import { setCurrentOrganization, switchOrganization } from "./organizationSlice";

const getOrgId = (value) => {
  if (value && typeof value === "object") {
    return value.orgId ?? value.organization_id ?? value.org_id ?? null;
  }
  return value ?? null;
};
export const fetchThreats = createAsyncThunk(
  "security/fetchThreats",
  async (orgId, { getState, rejectWithValue }) => {
    try {
      const response = await apiClient.get(
        `/security/threats?organization_id=${orgId}&status=all`,
      );
      return response.data;
    } catch (error) {
      return rejectWithValue(error.response?.data?.error);
    }
  },
);
export const fetchSecurityLogs = createAsyncThunk(
  "security/fetchLogs",
  async (orgId, { rejectWithValue }) => {
    try {
      const response = await apiClient.get(
        `/security/logs?organization_id=${orgId}`,
      );
      return response.data;
    } catch (error) {
      return rejectWithValue(error.response?.data?.error);
    }
  },
);
export const simulateAttack = createAsyncThunk(
  "security/simulateAttack",
  async (data, { rejectWithValue }) => {
    try {
      const response = await apiClient.post('/security/simulate-attack', data);
      return response.data;
    } catch (error) {
      return rejectWithValue(error.response?.data?.error);
    }
  },
);
export const fetchAlertRules = createAsyncThunk(
  "security/fetchAlertRules",
  async (orgId, { rejectWithValue }) => {
    try {
      const response = await apiClient.get(
        `/security/alert-rules?organization_id=${orgId}`,
      );
      return response.data;
    } catch (error) {
      return rejectWithValue(error.response?.data?.error);
    }
  },
);
export const createAlertRule = createAsyncThunk(
  "security/createAlertRule",
  async (data, { rejectWithValue }) => {
    try {
      const response = await apiClient.post("/security/alert-rules", data);
      return response.data;
    } catch (error) {
      return rejectWithValue(error.response?.data?.error);
    }
  },
);
export const updateAlertRule = createAsyncThunk(
  "security/updateAlertRule",
  async ({ ruleId, ...data }, { rejectWithValue }) => {
    try {
      const response = await apiClient.put(`/security/alert-rules/${ruleId}`, data);
      return response.data;
    } catch (error) {
      return rejectWithValue(error.response?.data?.error);
    }
  },
);
export const deleteAlertRule = createAsyncThunk(
  "security/deleteAlertRule",
  async ({ ruleId }, { rejectWithValue }) => {
    try {
      await apiClient.delete(`/security/alert-rules/${ruleId}`);
      return { ruleId };
    } catch (error) {
      return rejectWithValue(error.response?.data?.error);
    }
  },
);
const securitySlice = createSlice({
  name: "security",
  initialState: {
    activeOrgId: null,
    threats: [],
    logs: [],
    alertRules: [],
    loading: false,
    logsLoading: false,
    alertRulesLoading: false,
    alertRulesSaving: false,
    error: null,
    alertRulesError: null,
  },
  reducers: {
    clearSecurityState: (state) => {
      state.activeOrgId = null;
      state.threats = [];
      state.logs = [];
      state.alertRules = [];
      state.loading = false;
      state.logsLoading = false;
      state.alertRulesLoading = false;
      state.alertRulesSaving = false;
      state.error = null;
      state.alertRulesError = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(setCurrentOrganization, (state, action) => {
        state.activeOrgId = action.payload?.id ?? null;
        state.threats = [];
        state.logs = [];
        state.alertRules = [];
        state.loading = false;
        state.logsLoading = false;
        state.alertRulesLoading = false;
        state.alertRulesSaving = false;
        state.error = null;
        state.alertRulesError = null;
      })
      .addCase(switchOrganization, (state, action) => {
        state.activeOrgId = action.payload?.id ?? null;
        state.threats = [];
        state.logs = [];
        state.alertRules = [];
        state.loading = false;
        state.logsLoading = false;
        state.alertRulesLoading = false;
        state.alertRulesSaving = false;
        state.error = null;
        state.alertRulesError = null;
      })
      .addCase(fetchThreats.pending, (state, action) => {
        state.loading = true;
        state.activeOrgId = getOrgId(action.meta.arg);
      })
      .addCase(fetchThreats.fulfilled, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.loading = false;
        state.threats =
          action.payload?.threats || action.payload?.data?.threats || [];
      })
      .addCase(fetchThreats.rejected, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.loading = false;
        state.error = action.payload || action.error?.message || null;
      })
      .addCase(fetchSecurityLogs.pending, (state, action) => {
        state.logsLoading = true;
        state.activeOrgId = getOrgId(action.meta.arg);
      })
      .addCase(fetchSecurityLogs.fulfilled, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.logsLoading = false;
        state.logs = action.payload?.logs || action.payload?.data?.logs || [];
      })
      .addCase(fetchSecurityLogs.rejected, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.logsLoading = false;
        state.error = action.payload || action.error?.message || null;
      })
      .addCase(fetchAlertRules.pending, (state, action) => {
        state.alertRulesLoading = true;
        state.alertRulesError = null;
        state.activeOrgId = getOrgId(action.meta.arg);
      })
      .addCase(fetchAlertRules.fulfilled, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.alertRulesLoading = false;
        state.alertRules =
          action.payload?.data?.alert_rules || action.payload?.alert_rules || [];
      })
      .addCase(fetchAlertRules.rejected, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.alertRulesLoading = false;
        state.alertRulesError = action.payload || action.error?.message || null;
      })
      .addCase(createAlertRule.pending, (state) => {
        state.alertRulesSaving = true;
        state.alertRulesError = null;
      })
      .addCase(createAlertRule.fulfilled, (state, action) => {
        state.alertRulesSaving = false;
        const createdRule = action.payload?.data?.alert_rule;
        if (createdRule) {
          state.alertRules.unshift(createdRule);
        }
      })
      .addCase(createAlertRule.rejected, (state, action) => {
        state.alertRulesSaving = false;
        state.alertRulesError = action.payload || action.error?.message || null;
      })
      .addCase(updateAlertRule.pending, (state) => {
        state.alertRulesSaving = true;
        state.alertRulesError = null;
      })
      .addCase(updateAlertRule.fulfilled, (state, action) => {
        state.alertRulesSaving = false;
        const updatedRule = action.payload?.data?.alert_rule;
        if (!updatedRule) {
          return;
        }
        state.alertRules = state.alertRules.map((rule) =>
          rule.id === updatedRule.id ? updatedRule : rule,
        );
      })
      .addCase(updateAlertRule.rejected, (state, action) => {
        state.alertRulesSaving = false;
        state.alertRulesError = action.payload || action.error?.message || null;
      })
      .addCase(deleteAlertRule.pending, (state) => {
        state.alertRulesSaving = true;
        state.alertRulesError = null;
      })
      .addCase(deleteAlertRule.fulfilled, (state, action) => {
        state.alertRulesSaving = false;
        state.alertRules = state.alertRules.filter(
          (rule) => rule.id !== action.payload.ruleId,
        );
      })
      .addCase(deleteAlertRule.rejected, (state, action) => {
        state.alertRulesSaving = false;
        state.alertRulesError = action.payload || action.error?.message || null;
      });
  },
});
export const { clearSecurityState } = securitySlice.actions;
export default securitySlice.reducer;
