import React, { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import axios from "axios";
import toast from "react-hot-toast";
import { EyeIcon, EyeSlashIcon } from "@heroicons/react/24/outline";
import { switchOrganization } from "../../store/slices/organizationSlice";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:5000/api";

const LEVEL_TITLES = {
  1: "Cloud Curious",
  2: "Cloud Apprentice",
  3: "Cloud Practitioner",
  4: "Cloud Engineer",
  5: "Cloud Architect",
  6: "Cloud Expert",
};

const ROLE_BADGE = {
  owner: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
  admin: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  member: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
  viewer: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
};

const TIMEZONES = ["UTC", "PKT", "EST", "PST", "IST"];

export default function Profile() {
  const dispatch = useDispatch();
  const { token } = useSelector((state) => state.auth);
  const { organizations, currentOrganization } = useSelector((state) => state.organization);

  const [profileData, setProfileData] = useState(null);
  const [progress, setProgress] = useState(null);
  const [loadingProfile, setLoadingProfile] = useState(true);

  const [displayName, setDisplayName] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [savingProfile, setSavingProfile] = useState(false);

  const [currentPwd, setCurrentPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [changingPwd, setChangingPwd] = useState(false);

  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  useEffect(() => {
    if (!token) return;
    const fetchAll = async () => {
      setLoadingProfile(true);
      try {
        const [profRes, progRes] = await Promise.all([
          axios.get(`${API_URL}/auth/profile`, { headers }),
          axios.get(`${API_URL}/progress`, {
            headers,
            params: { organization_id: currentOrganization?.id },
          }),
        ]);
        const prof = profRes.data?.data || {};
        setProfileData(prof);
        setDisplayName(
          `${prof.user?.first_name || ""} ${prof.user?.last_name || ""}`.trim()
        );
        setTimezone(prof.profile?.timezone || "UTC");
        setProgress(progRes.data?.data || null);
      } catch {
        toast.error("Failed to load profile");
      } finally {
        setLoadingProfile(false);
      }
    };
    fetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const handleSaveProfile = async (e) => {
    e.preventDefault();
    setSavingProfile(true);
    try {
      await axios.put(
        `${API_URL}/auth/profile`,
        { display_name: displayName, timezone },
        { headers }
      );
      toast.success("Saved!");
    } catch (err) {
      toast.error(err?.response?.data?.error?.message || "Failed to save");
    } finally {
      setSavingProfile(false);
    }
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();
    if (newPwd !== confirmPwd) {
      toast.error("Passwords do not match");
      return;
    }
    if (newPwd.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    setChangingPwd(true);
    try {
      await axios.post(
        `${API_URL}/auth/change-password`,
        { current_password: currentPwd, new_password: newPwd },
        { headers }
      );
      toast.success("Password changed!");
      setCurrentPwd("");
      setNewPwd("");
      setConfirmPwd("");
    } catch (err) {
      toast.error(err?.response?.data?.error?.message || "Failed to change password");
    } finally {
      setChangingPwd(false);
    }
  };

  const user = profileData?.user || {};
  const initials = (user.first_name?.[0] || "?").toUpperCase();
  const level = progress?.level || 1;
  const levelTitle = LEVEL_TITLES[level] || "Cloud Expert";

  if (loadingProfile) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* SECTION 1 — Header */}
      <div className="card flex flex-col sm:flex-row items-center gap-6 p-6">
        <div className="h-20 w-20 shrink-0 rounded-full bg-primary-600 flex items-center justify-center text-3xl font-bold text-white">
          {initials}
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {user.first_name} {user.last_name}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">{user.email}</p>
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
            Member since{" "}
            {user.created_at
              ? new Date(user.created_at).toLocaleDateString()
              : "—"}
          </p>
        </div>
        {progress && (
          <span className="shrink-0 rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
            Level {level} — {levelTitle}
          </span>
        )}
      </div>

      {/* SECTION 2 — Stats */}
      {progress && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: "Total Points", value: progress.total_points ?? 0 },
            { label: "VMs Created", value: progress.vms_created ?? 0 },
            {
              label: "Scenarios Completed",
              value: (progress.scenarios_completed || []).length,
            },
            { label: "Login Streak", value: `${progress.login_streak ?? 0}d` },
          ].map(({ label, value }) => (
            <div key={label} className="card p-4 text-center">
              <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{label}</p>
            </div>
          ))}
        </div>
      )}

      {/* SECTION 3 — Organizations */}
      <div className="card p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Organizations
        </h2>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
            <thead>
              <tr className="text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                <th className="pb-2 pr-6">Name</th>
                <th className="pb-2 pr-6">Your Role</th>
                <th className="pb-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {organizations.map((org) => {
                const role = org.role || org.my_role || "member";
                const isActive = currentOrganization?.id === org.id;
                return (
                  <tr key={org.id} className={isActive ? "bg-primary-50 dark:bg-primary-900/10" : ""}>
                    <td className="py-3 pr-6 font-medium text-gray-900 dark:text-white">
                      {org.name}
                      {isActive && (
                        <span className="ml-2 text-xs text-primary-600 dark:text-primary-400">
                          (active)
                        </span>
                      )}
                    </td>
                    <td className="py-3 pr-6">
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${ROLE_BADGE[role] || ROLE_BADGE.member}`}>
                        {role}
                      </span>
                    </td>
                    <td className="py-3">
                      {!isActive && (
                        <button
                          type="button"
                          onClick={() => dispatch(switchOrganization(org))}
                          className="text-sm font-medium text-primary-600 hover:text-primary-800 dark:text-primary-400 dark:hover:text-primary-200"
                        >
                          Switch
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {organizations.length === 0 && (
                <tr>
                  <td colSpan={3} className="py-4 text-sm text-gray-400 dark:text-gray-500">
                    No organizations found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* SECTION 4 — Account Settings */}
      <div className="card p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Account Settings
        </h2>
        <form onSubmit={handleSaveProfile} className="space-y-4 max-w-md">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Display Name
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="input-field w-full"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Timezone
            </label>
            <select
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className="input-field w-full"
            >
              {TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>{tz}</option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={savingProfile}
            className="btn-primary"
          >
            {savingProfile ? "Saving..." : "Save"}
          </button>
        </form>
      </div>

      {/* SECTION 5 — Change Password */}
      <div className="card p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Change Password
        </h2>
        <form onSubmit={handleChangePassword} className="space-y-4 max-w-md">
          {[
            {
              label: "Current Password",
              value: currentPwd,
              setter: setCurrentPwd,
              show: showCurrent,
              toggle: () => setShowCurrent((v) => !v),
            },
            {
              label: "New Password",
              value: newPwd,
              setter: setNewPwd,
              show: showNew,
              toggle: () => setShowNew((v) => !v),
            },
            {
              label: "Confirm New Password",
              value: confirmPwd,
              setter: setConfirmPwd,
              show: showConfirm,
              toggle: () => setShowConfirm((v) => !v),
            },
          ].map(({ label, value, setter, show, toggle }) => (
            <div key={label}>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {label}
              </label>
              <div className="relative">
                <input
                  type={show ? "text" : "password"}
                  value={value}
                  onChange={(e) => setter(e.target.value)}
                  className="input-field w-full pr-10"
                  required
                />
                <button
                  type="button"
                  onClick={toggle}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                >
                  {show ? (
                    <EyeSlashIcon className="h-5 w-5" />
                  ) : (
                    <EyeIcon className="h-5 w-5" />
                  )}
                </button>
              </div>
            </div>
          ))}
          <button
            type="submit"
            disabled={changingPwd}
            className="btn-primary"
          >
            {changingPwd ? "Changing..." : "Change Password"}
          </button>
        </form>
      </div>
    </div>
  );
}
