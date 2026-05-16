import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import apiClient from '../../services/api';
import { setCurrentOrganization, switchOrganization } from './organizationSlice';

const getOrgId = (value) => {
  if (value && typeof value === 'object') {
    return value.orgId ?? value.organization_id ?? value.org_id ?? null;
  }
  return value ?? null;
};

export const fetchVMs = createAsyncThunk(
  'resources/fetchVMs',
  async (orgId, { getState, rejectWithValue }) => {
    try {
      const query = orgId ? `?org_id=${orgId}` : '';
      const response = await apiClient.get(`/resources/vms${query}`);
      const payload = response?.data?.data || {};
      return Array.isArray(payload?.vms) ? payload.vms : [];
    } catch (error) {
      return rejectWithValue(error?.response?.data?.error?.message || 'Failed to load resources');
    }
  }
);
export const fetchDatabases = createAsyncThunk(
  'resources/fetchDatabases',
  async (orgId, { getState, rejectWithValue }) => {
    try {
      const query = orgId ? `?org_id=${orgId}` : '';
      const response = await apiClient.get(`/resources/dbs${query}`);
      const payload = response?.data?.data || {};
      return Array.isArray(payload?.databases) ? payload.databases : [];
    } catch (error) {
      return rejectWithValue(error?.response?.data?.error?.message || 'Failed to load databases');
    }
  }
);
export const createVM = createAsyncThunk(
  'resources/createVM',
  async (data, { getState, rejectWithValue }) => {
    try {
      const response = await apiClient.post('/resources/vm', data);
      return response?.data?.data || {};
    } catch (error) {
      return rejectWithValue(error?.response?.data?.error?.message || 'Failed to create VM');
    }
  }
);
export const createDatabase = createAsyncThunk(
  'resources/createDatabase',
  async (data, { getState, rejectWithValue }) => {
    try {
      const response = await apiClient.post('/resources/db', data);
      return response?.data?.data || {};
    } catch (error) {
      return rejectWithValue(error?.response?.data?.error?.message || 'Failed to create database');
    }
  }
);
export const vmAction = createAsyncThunk(
  'resources/vmAction',
  async ({ instanceId, action }, { getState, rejectWithValue }) => {
    try {
      const response = await apiClient.post(
        `/resources/vm/${instanceId}/action`,
        { action }
      );
      return response?.data?.data || {};
    } catch (error) {
      return rejectWithValue(error?.response?.data?.error?.message || 'Failed VM action');
    }
  }
);
export const dbAction = createAsyncThunk(
  'resources/dbAction',
  async ({ instanceId, action }, { getState, rejectWithValue }) => {
    try {
      const response = await apiClient.post(
        `/resources/db/${instanceId}/action`,
        { action }
      );
      return response?.data?.data || {};
    } catch (error) {
      return rejectWithValue(error?.response?.data?.error?.message || 'Failed DB action');
    }
  }
);
const resourceSlice = createSlice({
  name: 'resources',
  initialState: {
    activeOrgId: null,
    vms: [],
    databases: [],
    metrics: null,
    loading: false,
    error: null,
  },
  reducers: {
    upsertVM: (state, action) => {
      const resource = action.payload;
      if (!resource) return;

      const id = resource.id || resource.instance_id;
      const type = resource.type === 'database' ? 'databases' : 'vms';
      const index = state[type].findIndex(v => v.id === id || v.instance_id === id);

      if (index !== -1) {
        state[type][index] = { ...state[type][index], ...resource };
      } else {
        state[type].push(resource);
      }
    },
    removeVM: (state, action) => {
      const id = action.payload;
      state.vms = state.vms.filter(v => v.id !== id && v.instance_id !== id);
      state.databases = state.databases.filter(d => d.id !== id && d.instance_id !== id);
    },
    clearResources: (state) => {
      state.activeOrgId = null;
      state.vms = [];
      state.databases = [];
      state.metrics = null;
      state.loading = false;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(setCurrentOrganization, (state, action) => {
        state.activeOrgId = action.payload?.id ?? null;
        state.vms = [];
        state.databases = [];
        state.metrics = null;
        state.loading = false;
        state.error = null;
      })
      .addCase(switchOrganization, (state, action) => {
        state.activeOrgId = action.payload?.id ?? null;
        state.vms = [];
        state.databases = [];
        state.metrics = null;
        state.loading = false;
        state.error = null;
      })
      .addCase(fetchVMs.pending, (state, action) => {
        state.loading = true;
        state.activeOrgId = getOrgId(action.meta.arg);
      })
      .addCase(fetchVMs.fulfilled, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.loading = false;
        state.vms = action.payload;
      })
      .addCase(fetchVMs.rejected, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.loading = false;
        state.error = action.payload;
        state.vms = [];
      })
      .addCase(fetchDatabases.pending, (state, action) => {
        state.loading = true;
        state.activeOrgId = getOrgId(action.meta.arg);
      })
      .addCase(fetchDatabases.fulfilled, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.loading = false;
        state.databases = action.payload;
      })
      .addCase(fetchDatabases.rejected, (state, action) => {
        if (state.activeOrgId !== getOrgId(action.meta.arg)) {
          return;
        }
        state.loading = false;
        state.error = action.payload;
        state.databases = [];
      })
      .addCase(createVM.fulfilled, (state, action) => {
        const orgId = action.payload?.vm?.organization_id ?? action.payload?.organization_id ?? null;
        if (state.activeOrgId !== null && orgId !== state.activeOrgId) {
          return;
        }
        state.vms.push(action.payload.vm);
      })
      .addCase(createDatabase.fulfilled, (state, action) => {
        const orgId = action.payload?.database?.organization_id ?? action.payload?.organization_id ?? null;
        if (state.activeOrgId !== null && orgId !== state.activeOrgId) {
          return;
        }
        state.databases.push(action.payload.database);
      });
  },
});
export const { upsertVM, removeVM, clearResources } = resourceSlice.actions;
export default resourceSlice.reducer;
