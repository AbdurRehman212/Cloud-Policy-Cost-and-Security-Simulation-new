import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';
const API_URL = 'http://localhost:5000/api';
export const fetchOrganizations = createAsyncThunk(
  'organization/fetchAll',
  async (_, { getState, rejectWithValue }) => {
    try {
      const token = getState().auth.token;
      const response = await axios.get(`${API_URL}/org/`, {
        headers: { Authorization: `Bearer ${token}` },
      });
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
      const token = getState().auth.token;
      const response = await axios.post(`${API_URL}/org/`, data, {
        headers: { Authorization: `Bearer ${token}` },
      });
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
    currentOrganization: null,
    loading: false,
    error: null,
  },
  reducers: {
    setCurrentOrganization: (state, action) => {
      state.currentOrganization = action.payload;
    },
    switchOrganization: (state, action) => {
      state.currentOrganization = action.payload;
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
        if (action.payload.length > 0 && !state.currentOrganization) {
          state.currentOrganization = action.payload[0];
        }
      })
      .addCase(createOrganization.fulfilled, (state, action) => {
        state.organizations.push(action.payload.organization);
      });
  },
});
export const { setCurrentOrganization, switchOrganization } = organizationSlice.actions;
export default organizationSlice.reducer;
