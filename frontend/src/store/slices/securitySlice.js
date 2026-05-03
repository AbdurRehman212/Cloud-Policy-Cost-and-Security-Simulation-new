import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import axios from "axios";
const API_URL = "http://localhost:5000/api";
export const fetchThreats = createAsyncThunk(
  "security/fetchThreats",
  async (orgId, { getState, rejectWithValue }) => {
    try {
      const token = getState().auth.token;
      const response = await axios.get(
        `${API_URL}/security/threats?organization_id=${orgId}&status=all`,
        {
          headers: { Authorization: `Bearer ${token}` },
        },
      );
      return response.data;
    } catch (error) {
      return rejectWithValue(error.response?.data?.error);
    }
  },
);
export const simulateAttack = createAsyncThunk(
  "security/simulateAttack",
  async (data, { getState, rejectWithValue }) => {
    try {
      const token = getState().auth.token;
      const response = await axios.post(
        `${API_URL}/security/simulate-attack`,
        data,
        {
          headers: { Authorization: `Bearer ${token}` },
        },
      );
      return response.data;
    } catch (error) {
      return rejectWithValue(error.response?.data?.error);
    }
  },
);
const securitySlice = createSlice({
  name: "security",
  initialState: {
    threats: [],
    logs: [],
    loading: false,
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder.addCase(fetchThreats.fulfilled, (state, action) => {
      state.threats =
        action.payload?.threats || action.payload?.data?.threats || [];
    });
  },
});
export default securitySlice.reducer;
