import React, { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import apiClient, { createSocket } from "../../services/api";
import {
  createAlertRule,
  deleteAlertRule,
  fetchAlertRules,
  fetchSecurityLogs,
  fetchThreats,
  simulateAttack,
  updateAlertRule,
} from "../../store/slices/securitySlice";
import LearningPanel from "../../components/Learning/LearningPanel";
import {
  ShieldCheckIcon,
  ExclamationTriangleIcon,
  BugAntIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";
const Security = () => {
  const dispatch = useDispatch();
  const { currentOrganization } = useSelector((state) => state.organization);
  const {
    threats,
    logs,
    alertRules,
    loading,
    logsLoading,
    alertRulesLoading,
    alertRulesSaving,
    error,
    alertRulesError,
  } = useSelector((state) => state.security);
  const activeOrgId = currentOrganization?.id;
  const canManageSecurity =
    currentOrganization?.my_role === "admin" ||
    currentOrganization?.my_role === "owner";
  const [showSimulateModal, setShowSimulateModal] = useState(false);
  const [attackType, setAttackType] = useState("ddos");
  const [learningActionKey, setLearningActionKey] = useState(null);
  const [resolvingThreatId, setResolvingThreatId] = useState(null);
  const [securityScore, setSecurityScore] = useState(null);
  const [securityScoreSource, setSecurityScoreSource] = useState("awaiting-backend-data");
  const [ruleDraft, setRuleDraft] = useState({
    name: "",
    conditionField: "severity",
    conditionOperator: "equals",
    conditionValue: "high",
    actionType: "IN_APP_NOTIFY",
  });
  const resolvedThreatCount = threats.filter(
    (threat) =>
      threat?.acknowledged === true ||
      threat?.status === "resolved" ||
      threat?.remediated === true,
  ).length;
  const activeThreatCount = threats.filter(
    (threat) => (threat?.status || "active") === "active",
  ).length;

  useEffect(() => {
    if (activeOrgId) {
      dispatch(fetchThreats(activeOrgId));
      dispatch(fetchSecurityLogs(activeOrgId));
      dispatch(fetchAlertRules(activeOrgId));
    }
  }, [dispatch, activeOrgId]);

  useEffect(() => {
    if (threats.length > 0) {
      localStorage.setItem("scenario:threat_viewed", "true");
    }
  }, [threats]);

  useEffect(() => {
    if (!activeOrgId) {
      setSecurityScore(null);
      setSecurityScoreSource("awaiting-backend-data");
      return undefined;
    }

    let cancelled = false;

    const loadSecurityOverview = async () => {
      try {
        const response = await apiClient.get("/dashboard/summary", {
          params: { organization_id: activeOrgId },
        });
        if (cancelled) return;
        const backendScore = response?.data?.security?.security_score;
        setSecurityScore(Number.isFinite(Number(backendScore)) ? Number(backendScore) : null);
        setSecurityScoreSource("dashboard-summary");
      } catch (error) {
        if (!cancelled) {
          setSecurityScore(null);
          setSecurityScoreSource("awaiting-backend-data");
        }
      }
    };

    loadSecurityOverview();

    return () => {
      cancelled = true;
    };
  }, [activeOrgId]);

  // Listen for real-time threats:update socket events
  useEffect(() => {
    if (!activeOrgId) return;
    const socket = createSocket("/metrics");
    if (!socket) return undefined;

    const handleConnect = () => {
      socket.emit("join_room", { org_id: activeOrgId });
    };
    const handleThreatsUpdate = () => {
      dispatch(fetchThreats(activeOrgId));
      dispatch(fetchSecurityLogs(activeOrgId));
      dispatch(fetchAlertRules(activeOrgId));
    };

    socket.on("connect", handleConnect);
    socket.on("threats:update", handleThreatsUpdate);
    if (socket.connected) {
      socket.emit("join_room", { org_id: activeOrgId });
    }
    return () => {
      socket.off("connect", handleConnect);
      socket.off("threats:update", handleThreatsUpdate);
    };
  }, [activeOrgId, dispatch]);

  const handleSimulate = async () => {
    const orgId = currentOrganization?.id;
    const result = await dispatch(
      simulateAttack({
        organization_id: orgId,
        attack_type: attackType,
      }),
    );
    if (result.meta.requestStatus === "fulfilled") {
      toast.success(
        `${attackType.toUpperCase()} attack simulated successfully`,
      );
      setShowSimulateModal(false);
      setLearningActionKey(
        attackType === "brute_force"
          ? "brute_force_attack"
          : attackType === "port_scan"
            ? "port_scan_attack"
            : "ddos_attack",
      );
      
      // Award points for attack simulation (backend defines points via XP_RULES)
      try {
        await apiClient.post(
          "/progress/award",
          { action: "attack_simulated", org_id: currentOrganization?.id },
        );
      } catch (awardError) {
        console.error("Failed to award points:", awardError);
      }
      
      // Wait for the backend commit + socket propagation, then refresh threats table
      setTimeout(() => dispatch(fetchThreats(activeOrgId)), 800);
    }
  };

  const handleResolveThreat = async (threatId) => {
    if (!activeOrgId || !threatId) return;

    setResolvingThreatId(threatId);
    try {
      await apiClient.post(`/security/threats/${threatId}/resolve`, {});
      localStorage.setItem("scenario:threat_resolved", "true");
      toast.success("Threat resolved");
      dispatch(fetchThreats(activeOrgId));
      dispatch(fetchSecurityLogs(activeOrgId));

      // Award XP for threat resolution (backend defines points via XP_RULES)
      try {
        await apiClient.post(
          "/progress/award",
          { action: "threat_resolved", org_id: activeOrgId },
        );
      } catch (awardError) {
        console.error("Failed to award XP:", awardError);
      }
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message ||
          error?.response?.data?.error ||
          "Unable to resolve threat",
      );
    } finally {
      setResolvingThreatId(null);
    }
  };

  const handleCreateAlertRule = async (event) => {
    event.preventDefault();
    if (!activeOrgId) return;

    const result = await dispatch(
      createAlertRule({
        organization_id: activeOrgId,
        name: ruleDraft.name,
        condition: {
          field: ruleDraft.conditionField,
          operator: ruleDraft.conditionOperator,
          value: ruleDraft.conditionValue,
        },
        action_type: ruleDraft.actionType,
      }),
    );

    if (result.meta.requestStatus === "fulfilled") {
      toast.success("Alert rule created");
      setRuleDraft({
        name: "",
        conditionField: "severity",
        conditionOperator: "equals",
        conditionValue: "high",
        actionType: "IN_APP_NOTIFY",
      });
    } else {
      toast.error(
        result.payload || result.error?.message || "Unable to create alert rule",
      );
    }
  };

  const handleToggleRule = async (rule) => {
    const result = await dispatch(
      updateAlertRule({
        ruleId: rule.id,
        is_active: !rule.is_active,
      }),
    );

    if (result.meta.requestStatus !== "fulfilled") {
      toast.error(
        result.payload || result.error?.message || "Unable to update alert rule",
      );
    }
  };

  const handleDeleteRule = async (ruleId) => {
    const result = await dispatch(deleteAlertRule({ ruleId }));
    if (result.meta.requestStatus === "fulfilled") {
      toast.success("Alert rule deleted");
      return;
    }

    toast.error(
      result.payload || result.error?.message || "Unable to delete alert rule",
    );
  };
  const getSeverityColor = (severity) => {
    switch (severity) {
      case "critical":
        return "bg-danger-100 text-danger-800 dark:bg-danger-900/20 dark:text-danger-400";
      case "high":
        return "bg-orange-100 text-orange-800 dark:bg-orange-900/20 dark:text-orange-400";
      case "medium":
        return "bg-warning-100 text-warning-800 dark:bg-warning-900/20 dark:text-warning-400";
      default:
        return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-400";
    }
  };
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Security Center
        </h1>
        {canManageSecurity ? (
          <button
            onClick={() => setShowSimulateModal(true)}
            className="btn-secondary flex items-center space-x-2"
          >
            <BugAntIcon className="w-5 h-5" />
            <span>Simulate Attack</span>
          </button>
        ) : (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Only admins and owners can simulate attacks or resolve threats.
          </p>
        )}
      </div>
      {/* Security Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                Security Score
              </p>
              {securityScore === null ? (
                <p className="text-lg font-semibold text-gray-500 dark:text-gray-400">
                  Awaiting backend data
                </p>
              ) : (
                <p className="text-3xl font-bold text-success-600">{securityScore}/100</p>
              )}
            </div>
            <ShieldCheckIcon className="w-12 h-12 text-success-500" />
          </div>
          <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
            Source: {securityScoreSource === "dashboard-summary" ? "dashboard snapshot" : "backend pending"}
          </p>
        </div>
        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                Active Threats
              </p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">
                {activeThreatCount}
              </p>
            </div>
            <ExclamationTriangleIcon className="w-12 h-12 text-warning-500" />
          </div>
        </div>
        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                Threats Resolved
              </p>
              <p className="text-3xl font-bold text-success-600">
                {resolvedThreatCount}
              </p>
            </div>
            <ShieldCheckIcon className="w-12 h-12 text-primary-500" />
          </div>
          <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
            Backend-acknowledged threat history.
          </p>
        </div>
      </div>
      {learningActionKey && (
        <LearningPanel
          action_key={learningActionKey}
          onClose={() => setLearningActionKey(null)}
        />
      )}
      {error && (
        <div className="rounded-lg border border-danger-100 bg-danger-50 px-4 py-3 text-sm text-danger-700 dark:border-danger-800 dark:bg-danger-900/20 dark:text-danger-100">
          {typeof error === "string" ? error : "Unable to load security threats."}
        </div>
      )}
      <div className="card">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Alert Rules
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Backend-owned rules applied to newly persisted threats in this organization.
            </p>
          </div>
          {alertRulesLoading && (
            <span className="text-sm text-gray-500 dark:text-gray-400">
              Loading...
            </span>
          )}
        </div>
        {alertRulesError && (
          <div className="mb-4 rounded-lg border border-danger-100 bg-danger-50 px-4 py-3 text-sm text-danger-700 dark:border-danger-800 dark:bg-danger-900/20 dark:text-danger-100">
            {typeof alertRulesError === "string"
              ? alertRulesError
              : "Unable to load alert rules."}
          </div>
        )}
        {canManageSecurity ? (
          <form className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-5" onSubmit={handleCreateAlertRule}>
            <input
              className="input-field md:col-span-2"
              value={ruleDraft.name}
              onChange={(event) =>
                setRuleDraft((current) => ({ ...current, name: event.target.value }))
              }
              placeholder="Rule name"
              required
            />
            <select
              className="input-field"
              value={ruleDraft.conditionField}
              onChange={(event) =>
                setRuleDraft((current) => ({
                  ...current,
                  conditionField: event.target.value,
                  conditionOperator:
                    event.target.value === "confidence_score" ? "greater_than" : "equals",
                  conditionValue:
                    event.target.value === "severity"
                      ? "high"
                      : event.target.value === "threat_type"
                        ? "ddos"
                        : "0.8",
                }))
              }
            >
              <option value="severity">Severity</option>
              <option value="threat_type">Threat Type</option>
              <option value="confidence_score">Confidence Score</option>
            </select>
            <select
              className="input-field"
              value={ruleDraft.conditionOperator}
              onChange={(event) =>
                setRuleDraft((current) => ({ ...current, conditionOperator: event.target.value }))
              }
            >
              {ruleDraft.conditionField === "confidence_score" ? (
                <>
                  <option value="greater_than">Greater than</option>
                  <option value="less_than">Less than</option>
                  <option value="equals">Equals</option>
                </>
              ) : (
                <>
                  <option value="equals">Equals</option>
                  <option value="contains">Contains</option>
                </>
              )}
            </select>
            <input
              className="input-field"
              value={ruleDraft.conditionValue}
              onChange={(event) =>
                setRuleDraft((current) => ({ ...current, conditionValue: event.target.value }))
              }
              placeholder={ruleDraft.conditionField === "confidence_score" ? "0.8" : "value"}
              required
            />
            <select
              className="input-field md:col-span-2"
              value={ruleDraft.actionType}
              onChange={(event) =>
                setRuleDraft((current) => ({ ...current, actionType: event.target.value }))
              }
            >
              <option value="IN_APP_NOTIFY">In-app notify</option>
              <option value="EMAIL_NOTIFY">Email notify</option>
              <option value="ISOLATE_RESOURCE">Isolate resource (simulated)</option>
              <option value="BLOCK_IP">Block IP (simulated)</option>
            </select>
            <button
              type="submit"
              className="btn-primary md:col-span-1"
              disabled={alertRulesSaving}
            >
              {alertRulesSaving ? "Saving..." : "Create Rule"}
            </button>
          </form>
        ) : (
          <p className="mb-6 text-sm text-gray-500 dark:text-gray-400">
            Members and viewers can review alert rules, but only admins and owners can change them.
          </p>
        )}
        <div className="space-y-3">
          {alertRules.length > 0 ? (
            alertRules.map((rule) => (
              <div
                key={rule.id}
                className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-4 dark:border-gray-700 dark:bg-gray-800/60"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-gray-900 dark:text-white">
                      {rule.name}
                    </p>
                    <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                      If <span className="font-medium">{rule.condition?.field}</span>{" "}
                      <span className="font-medium">{rule.condition?.operator}</span>{" "}
                      <span className="font-medium">{rule.condition?.value}</span>, then{" "}
                      <span className="font-medium">{rule.action_type}</span>.
                    </p>
                    {rule.description && (
                      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                        {rule.description}
                      </p>
                    )}
                  </div>
                  <div className="text-right">
                    <span
                      className={`rounded-full px-2 py-1 text-xs font-semibold ${
                        rule.is_active
                          ? "bg-success-100 text-success-700 dark:bg-success-900/20 dark:text-success-300"
                          : "bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300"
                      }`}
                    >
                      {rule.is_active ? "Active" : "Inactive"}
                    </span>
                    <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                      Triggered {rule.trigger_count} times
                    </p>
                  </div>
                </div>
                {canManageSecurity && (
                  <div className="mt-3 flex flex-wrap gap-3 text-sm">
                    <button
                      type="button"
                      className="text-primary-600 hover:underline disabled:opacity-60"
                      onClick={() => handleToggleRule(rule)}
                      disabled={alertRulesSaving}
                    >
                      {rule.is_active ? "Deactivate" : "Activate"}
                    </button>
                    <button
                      type="button"
                      className="text-danger-600 hover:underline disabled:opacity-60"
                      onClick={() => handleDeleteRule(rule.id)}
                      disabled={alertRulesSaving}
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            ))
          ) : (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              No alert rules configured for this organization yet.
            </p>
          )}
        </div>
      </div>
      {/* Threats Table */}
      <div className="card">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Detected Threats
          </h3>
          {loading && (
            <span className="text-sm text-gray-500 dark:text-gray-400">
              Loading...
            </span>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 dark:bg-gray-700">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  Detected At
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  Type
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  Severity
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  Confidence
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  Affected Resources
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {threats.map((threat) => (
                <tr
                  key={threat.id}
                  className="hover:bg-gray-50 dark:hover:bg-gray-700/50"
                >
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                    {new Date(threat.detected_at).toLocaleString()}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                    {threat.threat_type?.toUpperCase()}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span
                      className={`px-2 py-1 rounded-full text-xs font-semibold ${getSeverityColor(threat.severity)}`}
                    >
                      {threat.severity}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center">
                      <div className="w-16 bg-gray-200 dark:bg-gray-700 rounded-full h-2 mr-2">
                        <div
                          className="bg-primary-600 h-2 rounded-full"
                          style={{ width: `${threat.confidence_score * 100}%` }}
                        ></div>
                      </div>
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        {(threat.confidence_score * 100).toFixed(1)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span
                      className={`status-badge ${
                        threat.status === "active"
                          ? "status-critical"
                          : threat.status === "contained"
                            ? "status-warning"
                            : "status-running"
                      }`}
                    >
                      {threat.status}
                    </span>
                    {threat.status !== "resolved" && canManageSecurity && (
                        <button
                          type="button"
                          onClick={() => handleResolveThreat(threat.id)}
                          disabled={resolvingThreatId === threat.id}
                          className="mt-2 block text-xs font-medium text-primary-600 hover:underline disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {resolvingThreatId === threat.id
                            ? "Resolving..."
                            : "Resolve"}
                        </button>
                      )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {threat.affected_resources?.length || 0} resources
                  </td>
                </tr>
              ))}
              {threats.length === 0 && (
                <tr>
                  <td
                    colSpan="6"
                    className="px-6 py-8 text-center text-gray-500 dark:text-gray-400"
                  >
                    No persisted threats for this organization.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Recent Security Logs
          </h3>
          {logsLoading && (
            <span className="text-sm text-gray-500 dark:text-gray-400">
              Loading...
            </span>
          )}
        </div>
        <div className="space-y-3">
          {logs.length > 0 ? (
            logs.slice(0, 8).map((log) => (
              <div
                key={log.id}
                className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-800/60"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-gray-900 dark:text-white">
                      {log.event_type}
                    </p>
                    <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                      {log.description || "No description available."}
                    </p>
                  </div>
                  <span
                    className={`rounded-full px-2 py-1 text-xs font-semibold ${getSeverityColor(log.severity)}`}
                  >
                    {log.severity || "low"}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                  <span>{new Date(log.timestamp).toLocaleString()}</span>
                  {log.resource_id && <span>Resource: {log.resource_id}</span>}
                  {log.model_source && <span>Source: {log.model_source}</span>}
                  {log.alert_rule_name && <span>Rule: {log.alert_rule_name}</span>}
                  {log.action_status && <span>Action: {log.action_status}</span>}
                  {log.simulation && (
                    <span className="rounded-full bg-primary-100 px-2 py-0.5 text-primary-700 dark:bg-primary-900/20 dark:text-primary-300">
                      Simulation
                    </span>
                  )}
                </div>
              </div>
            ))
          ) : (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              No persisted security logs for this organization.
            </p>
          )}
        </div>
      </div>
      {/* Simulate Attack Modal */}
      {showSimulateModal && canManageSecurity && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-md mx-4">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
              Simulate Attack
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              This will simulate an attack for training purposes. The AI will
              detect and respond to the threat.
            </p>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Attack Type
                </label>
                <select
                  className="input-field"
                  value={attackType}
                  onChange={(e) => setAttackType(e.target.value)}
                >
                  <option value="ddos">DDoS Attack</option>
                  <option value="port_scan">Port Scan Attack</option>
                  <option value="brute_force">Brute Force Attack</option>
                </select>
              </div>
              <div className="flex justify-end space-x-3 pt-4">
                <button
                  onClick={() => setShowSimulateModal(false)}
                  className="btn-secondary"
                >
                  Cancel
                </button>
                <button onClick={handleSimulate} className="btn-danger">
                  Simulate Attack
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
export default Security;
