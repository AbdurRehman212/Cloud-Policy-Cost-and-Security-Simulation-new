import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import apiClient from '../../services/api';

const THEME_KEY = 'fyp:theme';

const message = (error, fallback) =>
  error?.response?.data?.error?.message || error?.response?.data?.error || fallback;

export const fetchSettings = createAsyncThunk('settings/fetch', async (_, { rejectWithValue }) => {
  try {
    const response = await apiClient.get('/settings');
    return response.data.data;
  } catch (error) {
    return rejectWithValue(message(error, 'Unable to load your settings.'));
  }
});

export const saveSettings = createAsyncThunk('settings/save', async (payload, { rejectWithValue }) => {
  try {
    const response = await apiClient.put('/settings', payload);
    return response.data.data;
  } catch (error) {
    return rejectWithValue(message(error, 'Settings were not saved.'));
  }
});

export const resetSettings = createAsyncThunk('settings/reset', async (_, { rejectWithValue }) => {
  try {
    const response = await apiClient.post('/settings/reset');
    return response.data.data;
  } catch (error) {
    return rejectWithValue(message(error, 'Defaults could not be restored.'));
  }
});

/** Apply the saved theme to the document; the cached copy avoids a flash on the next load. */
export const applyTheme = (theme) => {
  const dark = theme === 'dark';
  document.documentElement.classList.toggle('dark', dark);
  try {
    localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light');
  } catch (_ignored) {
    // storage unavailable (private mode); the server copy still applies on load
  }
};

export const applyCachedTheme = () => {
  try {
    document.documentElement.classList.toggle('dark', localStorage.getItem(THEME_KEY) === 'dark');
  } catch (_ignored) {
    // ignore
  }
};

const settingsSlice = createSlice({
  name: 'settings',
  initialState: { data: null, loading: false, saving: false, error: null },
  reducers: {
    clearSettings: (state) => {
      state.data = null;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    const stored = (state, action) => {
      state.data = action.payload;
      state.loading = false;
      state.saving = false;
      state.error = null;
      applyTheme(action.payload?.appearance?.theme);
    };
    builder
      .addCase(fetchSettings.pending, (state) => { state.loading = true; })
      .addCase(fetchSettings.fulfilled, stored)
      .addCase(fetchSettings.rejected, (state, action) => { state.loading = false; state.error = action.payload; })
      .addCase(saveSettings.pending, (state) => { state.saving = true; })
      .addCase(saveSettings.fulfilled, stored)
      .addCase(saveSettings.rejected, (state) => { state.saving = false; })
      .addCase(resetSettings.pending, (state) => { state.saving = true; })
      .addCase(resetSettings.fulfilled, stored)
      .addCase(resetSettings.rejected, (state) => { state.saving = false; });
  },
});

export const { clearSettings } = settingsSlice.actions;
export const selectDateFormat = (state) => state.settings?.data?.appearance?.date_format || 'YYYY-MM-DD';
export const selectDefaultView = (state) => {
  const view = state.settings?.data?.dashboard?.default_view;
  return view === 'list' ? 'list' : 'grid';
};
export default settingsSlice.reducer;
