import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import apiClient from '../../services/api';
export const fetchOrganizations = createAsyncThunk(
  'organization/fetchAll',
  async (_, { getState, rejectWithValue }) => {
    try {
      const response = await apiClient.get('/org/');
      return response?.data?.data?.organizations || [];
    } catch (error) {
      return rejectWithValue(error?.response?.data?.error?.message || 'Failed to load organizations');
    }
  }
);
export const createOrganization = createAsyncThunk(
  'organization/create',
  async (data, { getState, rejectWithValue }) => {
    try {
      const response = await apiClient.post('/org/', data);
      return response?.data?.data || {};
    } catch (error) {
      return rejectWithValue(error?.response?.data?.error?.message || 'Failed to create organization');
    }
  }
);
const organizationSlice = createSlice({
  name: 'organization',
  initialState: {
    organizations: [],
    currentOrganization: JSON.parse(localStorage.getItem('activeOrg')) || null,
    loading: false,
    error: null,
  },
  reducers: {
    setCurrentOrganization: (state, action) => {
      state.currentOrganization = action.payload;
    },
    switchOrganization: (state, action) => {
      state.currentOrganization = action.payload;
      localStorage.setItem('activeOrg', JSON.stringify(action.payload));
    },
    clearOrganizationState: (state) => {
      state.organizations = [];
      state.currentOrganization = null;
      state.loading = false;
      state.error = null;
      localStorage.removeItem('activeOrg');
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchOrganizations.pending, (state) => {
        state.loading = true;
      })
      .addCase(fetchOrganizations.fulfilled, (state, action) => {
        state.loading = false;
        state.organizations = action.payload;
        const saved = JSON.parse(localStorage.getItem('activeOrg'));
        if (saved) {
          const refreshed = action.payload.find(o => o.id === saved.id);
          state.currentOrganization = refreshed || action.payload[0] || null;
        } else if (!state.currentOrganization && action.payload.length > 0) {
          state.currentOrganization = action.payload[0];
        }
        if (state.currentOrganization) {
          localStorage.setItem('activeOrg', JSON.stringify(state.currentOrganization));
        }
      })
      .addCase(createOrganization.fulfilled, (state, action) => {
        state.organizations.push(action.payload.organization);
      });
  },
});
export const { setCurrentOrganization, switchOrganization, clearOrganizationState } = organizationSlice.actions;
export default organizationSlice.reducer;
