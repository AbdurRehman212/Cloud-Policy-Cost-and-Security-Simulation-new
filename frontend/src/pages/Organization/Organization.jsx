import React, { useCallback, useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import toast from "react-hot-toast";
import { fetchOrganizations } from "../../store/slices/organizationSlice";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:5000/api";

const ROLE_BADGE = {
  owner: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
  admin: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  member: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
  viewer: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
};

const QuotaBar = ({ label, used, limit }) => {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const color =
    pct > 90
      ? "bg-red-500"
      : pct > 70
      ? "bg-yellow-400"
      : "bg-green-500";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="font-medium text-gray-700 dark:text-gray-300">{label}</span>
        <span className="text-gray-500 dark:text-gray-400">
          {used} / {limit}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
};

export default function Organization() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const { token } = useSelector((state) => state.auth);
  const { currentOrganization } = useSelector((state) => state.organization);
  const orgId = currentOrganization?.id;
  const myRole = currentOrganization?.role || currentOrganization?.my_role;

  const [tab, setTab] = useState("overview");
  const [orgDetail, setOrgDetail] = useState(null);
  const [quotas, setQuotas] = useState(null);
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviting, setInviting] = useState(false);

  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [savingOrg, setSavingOrg] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);

  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  const loadData = useCallback(async () => {
    if (!orgId) return;
    setLoading(true);
    try {
      const [detailRes, quotaRes, membersRes] = await Promise.all([
        axios.get(`${API_URL}/org/${orgId}`, { headers }),
        axios.get(`${API_URL}/org/${orgId}/quotas`, { headers }),
        axios.get(`${API_URL}/org/${orgId}/members`, { headers }),
      ]);
      const detail = detailRes.data?.data || {};
      setOrgDetail(detail);
      setEditName(detail.name || "");
      setEditDesc(detail.description || "");
      setQuotas(quotaRes.data?.data || null);
      setMembers(membersRes.data?.data?.members || []);
    } catch {
      toast.error("Failed to load organization data");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleUpdateRole = async (targetUserId, role) => {
    try {
      await axios.put(
        `${API_URL}/org/${orgId}/members/${targetUserId}/role`,
        { role },
        { headers }
      );
      toast.success("Role updated");
      loadData();
    } catch (err) {
      toast.error(err?.response?.data?.error?.message || "Failed to update role");
    }
  };

  const handleRemoveMember = async (memberId, name) => {
    if (!window.confirm(`Remove ${name} from this organization?`)) return;
    try {
      await axios.delete(`${API_URL}/org/${orgId}/members/${memberId}`, { headers });
      toast.success("Member removed");
      loadData();
    } catch (err) {
      toast.error(err?.response?.data?.error?.message || "Failed to remove member");
    }
  };

  const handleInvite = async (e) => {
    e.preventDefault();
    setInviting(true);
    try {
      await axios.post(
        `${API_URL}/org/invite_demo`,
        { email: inviteEmail, role: inviteRole, organization_id: orgId },
        { headers }
      );
      toast.success(`Invited ${inviteEmail}`);
      setInviteEmail("");
      setInviteOpen(false);
      loadData();
    } catch (err) {
      toast.error(err?.response?.data?.error?.message || "Failed to invite");
    } finally {
      setInviting(false);
    }
  };

  const handleSaveOrg = async (e) => {
    e.preventDefault();
    setSavingOrg(true);
    try {
      await axios.put(
        `${API_URL}/org/${orgId}`,
        { name: editName, description: editDesc },
        { headers }
      );
      toast.success("Organization updated");
      dispatch(fetchOrganizations());
    } catch (err) {
      toast.error(err?.response?.data?.error?.message || "Failed to update");
    } finally {
      setSavingOrg(false);
    }
  };

  const handleDeleteOrg = async () => {
    if (deleteConfirm !== orgDetail?.name) {
      toast.error("Type the organization name to confirm");
      return;
    }
    setDeleting(true);
    try {
      await axios.delete(`${API_URL}/org/${orgId}`, { headers });
      toast.success("Organization deleted");
      dispatch(fetchOrganizations());
      navigate("/");
    } catch (err) {
      toast.error(err?.response?.data?.error?.message || "Failed to delete");
    } finally {
      setDeleting(false);
    }
  };

  if (!orgId) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-500 dark:text-gray-400">No organization selected.</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary-600" />
      </div>
    );
  }

  const canManage = myRole === "owner" || myRole === "admin";

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          {orgDetail?.name}
        </h1>
        <div className="mt-1 flex items-center gap-2">
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${ROLE_BADGE[myRole] || ROLE_BADGE.member}`}>
            {myRole}
          </span>
          {orgDetail?.created_at && (
            <span className="text-xs text-gray-400 dark:text-gray-500">
              Created {new Date(orgDetail.created_at).toLocaleDateString()}
            </span>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-gray-200 dark:border-gray-700">
        {["overview", "members", ...(myRole === "owner" ? ["settings"] : [])].map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${
              tab === t
                ? "border-primary-600 text-primary-600"
                : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* TAB: Overview */}
      {tab === "overview" && (
        <div className="space-y-6">
          {orgDetail?.description && (
            <p className="text-gray-600 dark:text-gray-300">{orgDetail.description}</p>
          )}
          {quotas && (
            <div className="card p-6 space-y-4">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Resource Quotas
              </h2>
              <QuotaBar label="Virtual Machines" used={quotas.vms?.used ?? 0} limit={quotas.vms?.limit ?? 20} />
              <QuotaBar label="Databases" used={quotas.databases?.used ?? 0} limit={quotas.databases?.limit ?? 10} />
              <QuotaBar label="Storage (GB)" used={quotas.storage?.used ?? 0} limit={quotas.storage?.limit ?? 100} />
              <div>
                <div className="mb-1 flex items-center justify-between text-sm">
                  <span className="font-medium text-gray-700 dark:text-gray-300">Budget</span>
                  <span className="text-gray-500 dark:text-gray-400">
                    ${(quotas.budget?.used ?? 0).toFixed(2)} / ${quotas.budget?.limit ?? 1000}
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                  {(() => {
                    const pct = Math.min(100, ((quotas.budget?.used ?? 0) / (quotas.budget?.limit ?? 1000)) * 100);
                    const color = pct > 90 ? "bg-red-500" : pct > 70 ? "bg-yellow-400" : "bg-green-500";
                    return <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />;
                  })()}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB: Members */}
      {tab === "members" && (
        <div className="space-y-4">
          {canManage && (
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setInviteOpen(true)}
                className="btn-primary"
              >
                + Invite Member
              </button>
            </div>
          )}

          {inviteOpen && (
            <div className="card p-5">
              <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-3">
                Invite Member
              </h3>
              <form onSubmit={handleInvite} className="flex flex-wrap gap-3 items-end">
                <div>
                  <label className="block text-sm text-gray-600 dark:text-gray-400 mb-1">Email</label>
                  <input
                    type="email"
                    required
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    className="input-field"
                    placeholder="user@example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-600 dark:text-gray-400 mb-1">Role</label>
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value)}
                    className="input-field"
                  >
                    <option value="member">member</option>
                    <option value="viewer">viewer</option>
                    <option value="admin">admin</option>
                  </select>
                </div>
                <button type="submit" disabled={inviting} className="btn-primary">
                  {inviting ? "Inviting..." : "Send Invite"}
                </button>
                <button
                  type="button"
                  onClick={() => setInviteOpen(false)}
                  className="btn-secondary"
                >
                  Cancel
                </button>
              </form>
            </div>
          )}

          <div className="card overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
              <thead className="bg-gray-50 dark:bg-gray-800">
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  <th className="px-4 py-3">Member</th>
                  <th className="px-4 py-3">Email</th>
                  <th className="px-4 py-3">Role</th>
                  {canManage && <th className="px-4 py-3">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {members.map((m) => (
                  <tr key={m.id}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="h-8 w-8 shrink-0 rounded-full bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center text-sm font-semibold text-primary-700 dark:text-primary-300">
                          {(m.name?.[0] || "?").toUpperCase()}
                        </div>
                        <span className="font-medium text-gray-900 dark:text-white">
                          {m.name}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400">{m.email}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${ROLE_BADGE[m.role] || ROLE_BADGE.member}`}>
                        {m.role}
                      </span>
                    </td>
                    {canManage && (
                      <td className="px-4 py-3">
                        {m.role !== "owner" && (
                          <div className="flex items-center gap-2">
                            <select
                              value={m.role}
                              onChange={(e) => handleUpdateRole(m.user_id, e.target.value)}
                              className="rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-xs"
                            >
                              {["member", "viewer", "admin"].map((r) => (
                                <option key={r} value={r}>{r}</option>
                              ))}
                            </select>
                            <button
                              type="button"
                              onClick={() => handleRemoveMember(m.id, m.name)}
                              className="text-xs text-red-600 hover:underline dark:text-red-400"
                            >
                              Remove
                            </button>
                          </div>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
                {members.length === 0 && (
                  <tr>
                    <td colSpan={canManage ? 4 : 3} className="px-4 py-6 text-center text-gray-400">
                      No members found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB: Settings (owner only) */}
      {tab === "settings" && myRole === "owner" && (
        <div className="space-y-6">
          <div className="card p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Edit Organization
            </h2>
            <form onSubmit={handleSaveOrg} className="space-y-4 max-w-md">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Name
                </label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="input-field w-full"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  className="input-field w-full min-h-[80px]"
                />
              </div>
              <button type="submit" disabled={savingOrg} className="btn-primary">
                {savingOrg ? "Saving..." : "Save Changes"}
              </button>
            </form>
          </div>

          <div className="card border border-red-200 dark:border-red-800 p-6">
            <h2 className="text-lg font-semibold text-red-700 dark:text-red-400 mb-2">
              Danger Zone
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              Permanently deletes the organization. Type{" "}
              <strong>{orgDetail?.name}</strong> to confirm.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="text"
                value={deleteConfirm}
                onChange={(e) => setDeleteConfirm(e.target.value)}
                placeholder={orgDetail?.name}
                className="input-field"
              />
              <button
                type="button"
                disabled={deleteConfirm !== orgDetail?.name || deleting}
                onClick={handleDeleteOrg}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {deleting ? "Deleting..." : "Delete Organization"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
