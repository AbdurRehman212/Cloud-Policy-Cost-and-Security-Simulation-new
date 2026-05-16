import React, { useEffect, useMemo, useState } from "react";
import { useSelector } from "react-redux";
import {
  ClipboardDocumentCheckIcon,
  ExclamationTriangleIcon,
  PlusIcon,
  ShieldCheckIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";

import LearningPanel from "../../components/Learning/LearningPanel";
import apiClient from "../../services/api";

const Governance = () => {
  const { currentOrganization } = useSelector((state) => state.organization);
  const canManagePolicies =
    currentOrganization?.my_role === "admin" ||
    currentOrganization?.my_role === "owner";

  const [policies, setPolicies] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [recentChecks, setRecentChecks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [runningCheck, setRunningCheck] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newPolicy, setNewPolicy] = useState({
    name: "",
    description: "",
    policy_rule: "",
    auto_remediate: false,
  });
  const [complianceResults, setComplianceResults] = useState(null);
  const [learningActionKey, setLearningActionKey] = useState(null);

  const orgId = currentOrganization?.id;

  const loadGovernanceData = async () => {
    if (!orgId) {
      setPolicies([]);
      setAuditLogs([]);
      setRecentChecks([]);
      setComplianceResults(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const [policiesResponse, auditResponse, checksResponse] = await Promise.all([
        apiClient.get("/governance/policies", {
          params: { organization_id: orgId },
        }),
        apiClient.get("/governance/audit-logs", {
          params: { organization_id: orgId },
        }),
        apiClient.get("/governance/compliance/checks", {
          params: { organization_id: orgId, limit: 20 },
        }),
      ]);

      setPolicies(policiesResponse?.data?.data?.policies || []);
      setAuditLogs(auditResponse?.data?.data?.logs || []);
      setRecentChecks(checksResponse?.data?.data?.checks || []);
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Failed to load governance data",
      );
      setPolicies([]);
      setAuditLogs([]);
      setRecentChecks([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadGovernanceData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  const complianceSummary = useMemo(() => {
    if (!complianceResults) return null;
    return {
      score: Number(complianceResults.compliance_score ?? 100),
      violations: Number(complianceResults.violations_found ?? 0),
      checked: Number(complianceResults.resources_evaluated ?? 0),
      policies: Number(complianceResults.policies_checked ?? 0),
    };
  }, [complianceResults]);

  const handleCreatePolicy = async (event) => {
    event.preventDefault();
    try {
      await apiClient.post("/governance/policies", {
        ...newPolicy,
        organization_id: orgId,
      });
      try {
        await apiClient.post("/progress/award", {
          action: "policy_created",
          org_id: orgId,
        });
      } catch (_error) {
        // Governance is complete even if XP fails.
      }

      toast.success("Policy created successfully");
      setShowCreateModal(false);
      setNewPolicy({
        name: "",
        description: "",
        policy_rule: "",
        auto_remediate: false,
      });
      await loadGovernanceData();
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Failed to create policy",
      );
    }
  };

  const runComplianceCheck = async () => {
    if (!orgId) return;
    setRunningCheck(true);
    try {
      const response = await apiClient.post("/governance/compliance/check", {
        organization_id: orgId,
      });
      const result = response?.data?.data || null;
      setComplianceResults(result);
      setLearningActionKey("compliance_check");
      toast.success(
        `Compliance score ${Number(result?.compliance_score ?? 100).toFixed(1)} with ${result?.violations_found ?? 0} violation(s)`,
      );
      await loadGovernanceData();
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Compliance check failed",
      );
    } finally {
      setRunningCheck(false);
    }
  };

  const getPolicyTypeColor = (type) => {
    const colors = {
      security: "bg-danger-100 text-danger-800 dark:bg-danger-900/20 dark:text-danger-300",
      naming: "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-300",
      tagging: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300",
      compliance: "bg-success-100 text-success-800 dark:bg-success-900/20 dark:text-success-300",
      custom: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
    };
    return colors[type] || colors.custom;
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Governance & Compliance
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Backend-owned policy compilation, org-scoped compliance evaluation, and persisted audit history.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={runComplianceCheck}
            disabled={!orgId || runningCheck}
            className="btn-secondary flex items-center space-x-2 disabled:opacity-50"
          >
            <ShieldCheckIcon className="w-5 h-5" />
            <span>{runningCheck ? "Running..." : "Run Compliance Check"}</span>
          </button>
          {canManagePolicies && (
            <button
              onClick={() => setShowCreateModal(true)}
              className="btn-primary flex items-center space-x-2"
            >
              <PlusIcon className="w-5 h-5" />
              <span>Create Policy</span>
            </button>
          )}
        </div>
      </div>

      {learningActionKey && (
        <LearningPanel
          action_key={learningActionKey}
          onClose={() => setLearningActionKey(null)}
        />
      )}

      {!canManagePolicies && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
          You can view policies, compliance results, and audit history, but only admins and owners can create or modify policies.
        </div>
      )}

      {complianceSummary && (
        <div className="card border-primary-200 bg-primary-50 dark:border-primary-800 dark:bg-primary-900/20">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="text-lg font-semibold text-primary-900 dark:text-primary-100">
                Compliance Check Complete
              </h3>
              <p className="mt-1 text-sm text-primary-700 dark:text-primary-300">
                Score {complianceSummary.score.toFixed(1)} across {complianceSummary.checked} evaluated resources and {complianceSummary.policies} active policies.
              </p>
            </div>
            <div className="flex flex-wrap gap-3 text-sm">
              <span className="rounded-full bg-white px-3 py-1 font-semibold text-primary-700 dark:bg-gray-800 dark:text-primary-300">
                Violations: {complianceSummary.violations}
              </span>
              <button
                onClick={() => setComplianceResults(null)}
                className="text-primary-700 underline hover:text-primary-900 dark:text-primary-300 dark:hover:text-primary-100"
              >
                Dismiss
              </button>
            </div>
          </div>
          {complianceResults?.results?.length > 0 ? (
            <div className="mt-4 space-y-3">
              {complianceResults.results.map((result, index) => (
                <div
                  key={`${result.policy_id}-${result.resource_id}-${index}`}
                  className="rounded-lg bg-white px-4 py-3 dark:bg-gray-800"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium text-gray-900 dark:text-white">
                      {result.policy_name} on {result.resource_type} {result.resource_id}
                    </p>
                    <span className="rounded-full bg-red-100 px-2 py-1 text-xs font-semibold text-red-700 dark:bg-red-900/20 dark:text-red-300">
                      {result.severity}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-red-600 dark:text-red-300">
                    {result.violations.join(", ")}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-4 text-sm text-primary-700 dark:text-primary-300">
              No violations were detected in the latest compliance run.
            </p>
          )}
        </div>
      )}

      {loading ? (
        <div className="card py-16 text-center text-gray-500 dark:text-gray-400">
          Loading governance data...
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <div className="xl:col-span-2 space-y-6">
              <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                {policies.map((policy) => (
                  <div
                    key={policy.id}
                    className="card hover:shadow-md transition-shadow"
                  >
                    <div className="mb-4 flex items-start justify-between">
                      <span
                        className={`rounded-full px-2 py-1 text-xs font-semibold ${getPolicyTypeColor(policy.policy_type)}`}
                      >
                        {policy.policy_type || "custom"}
                      </span>
                      <span
                        className={`rounded-full px-2 py-1 text-xs font-semibold ${
                          policy.auto_remediate
                            ? "bg-success-100 text-success-800 dark:bg-success-900/20 dark:text-success-300"
                            : "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300"
                        }`}
                      >
                        {policy.auto_remediate ? "Auto-remediate" : "Manual"}
                      </span>
                    </div>
                    <h3 className="mb-2 text-lg font-semibold text-gray-900 dark:text-white">
                      {policy.name}
                    </h3>
                    <p className="mb-4 text-sm text-gray-600 dark:text-gray-400">
                      {policy.description || "No description provided."}
                    </p>
                    <div className="rounded-lg bg-gray-50 p-3 dark:bg-gray-700/50">
                      <p className="mb-1 text-xs font-semibold uppercase text-gray-500 dark:text-gray-400">
                        Rule
                      </p>
                      <p className="text-sm italic text-gray-700 dark:text-gray-300">
                        "{policy.policy_rule}"
                      </p>
                    </div>
                    <div className="mt-4 flex items-center justify-between text-sm">
                      <span className="text-gray-500 dark:text-gray-400">
                        Severity:{" "}
                        <span className="font-medium capitalize">{policy.severity}</span>
                      </span>
                      <span
                        className={`rounded px-2 py-1 text-xs ${
                          policy.status === "active"
                            ? "bg-success-100 text-success-800 dark:bg-success-900/20 dark:text-success-300"
                            : "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300"
                        }`}
                      >
                        {policy.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>

              {policies.length === 0 && (
                <div className="card py-12 text-center">
                  <ClipboardDocumentCheckIcon className="mx-auto mb-4 h-16 w-16 text-gray-300" />
                  <h3 className="mb-2 text-lg font-medium text-gray-900 dark:text-white">
                    No policies yet
                  </h3>
                  <p className="mb-4 text-gray-500 dark:text-gray-400">
                    Create a policy to compile naming, tagging, encryption, or public-access rules on the backend.
                  </p>
                  {canManagePolicies && (
                    <button
                      onClick={() => setShowCreateModal(true)}
                      className="btn-primary"
                    >
                      Create Policy
                    </button>
                  )}
                </div>
              )}
            </div>

            <div className="space-y-6">
              <div className="card">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Recent Compliance Checks
                </h3>
                <div className="mt-4 space-y-3">
                  {recentChecks.length > 0 ? (
                    recentChecks.slice(0, 8).map((check) => (
                      <div
                        key={check.id}
                        className="rounded-lg border border-gray-200 px-3 py-3 dark:border-gray-700"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-gray-900 dark:text-white">
                              {check.policy_name}
                            </p>
                            <p className="text-xs text-gray-500 dark:text-gray-400">
                              {check.resource_type} {check.resource_id}
                            </p>
                          </div>
                          <span
                            className={`rounded-full px-2 py-1 text-xs font-semibold ${
                              check.is_compliant
                                ? "bg-success-100 text-success-800 dark:bg-success-900/20 dark:text-success-300"
                                : "bg-red-100 text-red-700 dark:bg-red-900/20 dark:text-red-300"
                            }`}
                          >
                            {check.is_compliant ? "Compliant" : "Violation"}
                          </span>
                        </div>
                        {!check.is_compliant && (
                          <p className="mt-2 text-sm text-red-600 dark:text-red-300">
                            {(check.violation_details?.violations || []).join(", ")}
                          </p>
                        )}
                      </div>
                    ))
                  ) : (
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      No persisted compliance checks yet.
                    </p>
                  )}
                </div>
              </div>

              <div className="card">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Governance Audit History
                </h3>
                <div className="mt-4 space-y-3">
                  {auditLogs.filter((log) => String(log.resource_type || "").includes("policy") || String(log.action || "").startsWith("policy_")).length > 0 ? (
                    auditLogs
                      .filter((log) => String(log.resource_type || "").includes("policy") || String(log.action || "").startsWith("policy_"))
                      .slice(0, 8)
                      .map((log) => (
                        <div
                          key={log.id}
                          className="rounded-lg border border-gray-200 px-3 py-3 dark:border-gray-700"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-gray-900 dark:text-white">
                              {log.action}
                            </p>
                            <span className="text-xs text-gray-500 dark:text-gray-400">
                              {log.timestamp ? new Date(log.timestamp).toLocaleString() : "Unknown time"}
                            </span>
                          </div>
                          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                            Resource {log.resource_id || "n/a"}
                          </p>
                        </div>
                      ))
                  ) : (
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      No governance audit history yet.
                    </p>
                  )}
                </div>
              </div>

              {!complianceSummary && (
                <div className="rounded-xl border border-dashed border-gray-300 bg-white px-4 py-4 dark:border-gray-700 dark:bg-gray-800">
                  <div className="flex items-start gap-3">
                    <ExclamationTriangleIcon className="mt-0.5 h-5 w-5 text-amber-500" />
                    <p className="text-sm text-gray-600 dark:text-gray-300">
                      No live compliance score is shown until the backend runs an evaluation for the current organization.
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {showCreateModal && canManagePolicies && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="mx-4 max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-6 dark:bg-gray-800">
            <h2 className="mb-4 text-xl font-bold text-gray-900 dark:text-white">
              Create Governance Policy
            </h2>
            <form onSubmit={handleCreatePolicy} className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Policy Name
                </label>
                <input
                  type="text"
                  required
                  className="input-field"
                  value={newPolicy.name}
                  onChange={(event) =>
                    setNewPolicy({ ...newPolicy, name: event.target.value })
                  }
                  placeholder="Encrypt production databases"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Description
                </label>
                <textarea
                  className="input-field"
                  rows="2"
                  value={newPolicy.description}
                  onChange={(event) =>
                    setNewPolicy({ ...newPolicy, description: event.target.value })
                  }
                  placeholder="Describe what this policy checks and why."
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Policy Rule
                </label>
                <textarea
                  required
                  className="input-field"
                  rows="4"
                  value={newPolicy.policy_rule}
                  onChange={(event) =>
                    setNewPolicy({ ...newPolicy, policy_rule: event.target.value })
                  }
                  placeholder="Examples: all databases must be encrypted; all VMs must have tag Environment:Production; VM names must start with web-"
                />
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  The backend supports deterministic key=value rules and a small set of natural-language compliance patterns.
                </p>
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  id="auto_remediate"
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                  checked={newPolicy.auto_remediate}
                  onChange={(event) =>
                    setNewPolicy({
                      ...newPolicy,
                      auto_remediate: event.target.checked,
                    })
                  }
                />
                <label
                  htmlFor="auto_remediate"
                  className="ml-2 text-sm text-gray-700 dark:text-gray-300"
                >
                  Mark policy for auto-remediation metadata
                </label>
              </div>
              <div className="flex justify-end space-x-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="btn-secondary"
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Create Policy
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default Governance;
