import React, { useState, useEffect } from "react";
import { useSelector } from "react-redux";
import {
  ClipboardDocumentCheckIcon,
  PlusIcon,
  ShieldCheckIcon,
} from "@heroicons/react/24/outline";
import axios from "axios";
import toast from "react-hot-toast";
import LearningPanel from "../../components/Learning/LearningPanel";
const API_URL = "http://localhost:5000/api";
const Governance = () => {
  const { currentOrganization } = useSelector((state) => state.organization);
  const { token } = useSelector((state) => state.auth);
  const [policies, setPolicies] = useState([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newPolicy, setNewPolicy] = useState({
    name: "",
    description: "",
    policy_rule: "",
    auto_remediate: false,
  });
  const [complianceResults, setComplianceResults] = useState(null);
  const [learningActionKey, setLearningActionKey] = useState(null);
  useEffect(() => {
    const loadPolicies = async () => {
      try {
        const response = await axios.get(
          `${API_URL}/governance/policies?organization_id=${currentOrganization.id}`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        setPolicies(response.data.policies);
      } catch (error) {
        toast.error("Failed to fetch policies");
      }
    };

    if (currentOrganization) {
      loadPolicies();
    }
  }, [currentOrganization, token]);
  const fetchPolicies = async () => {
    try {
      const response = await axios.get(
        `${API_URL}/governance/policies?organization_id=${currentOrganization.id}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      setPolicies(response.data.policies);
    } catch (error) {
      toast.error("Failed to fetch policies");
    }
  };
  const handleCreatePolicy = async (e) => {
    e.preventDefault();
    try {
      await axios.post(
        `${API_URL}/governance/policies`,
        {
          ...newPolicy,
          organization_id: currentOrganization.id,
        },
        { headers: { Authorization: `Bearer ${token}` } },
      );
      
      // Award points for policy creation
      try {
        await axios.post(
          `${API_URL}/progress/award`,
          {
            action: "policy_created",
            points: 15,
            org_id: currentOrganization.id,
          },
          { headers: { Authorization: `Bearer ${token}` } },
        );
      } catch (awardError) {
        console.error("Failed to award points:", awardError);
      }
      
      toast.success("Policy created successfully");
      setShowCreateModal(false);
      setNewPolicy({
        name: "",
        description: "",
        policy_rule: "",
        auto_remediate: false,
      });
      fetchPolicies();
    } catch (error) {
      toast.error(error.response?.data?.error || "Failed to create policy");
    }
  };
  const runComplianceCheck = async () => {
    try {
      const response = await axios.post(
        `${API_URL}/governance/compliance/check`,
        { organization_id: currentOrganization.id },
        { headers: { Authorization: `Bearer ${token}` } },
      );
      setComplianceResults(response.data);
      toast.success(`Found ${response.data.violations_found} violations`);
      setLearningActionKey("compliance_check");
    } catch (error) {
      toast.error("Compliance check failed");
    }
  };
  const getPolicyTypeColor = (type) => {
    const colors = {
      security: "bg-danger-100 text-danger-800",
      governance: "bg-primary-100 text-primary-800",
      cost: "bg-warning-100 text-warning-800",
      compliance: "bg-success-100 text-success-800",
    };
    return colors[type] || "bg-gray-100 text-gray-800";
  };
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Governance & Compliance
        </h1>
        <div className="flex space-x-3">
          <button
            onClick={runComplianceCheck}
            className="btn-secondary flex items-center space-x-2"
          >
            <ShieldCheckIcon className="w-5 h-5" />
            <span>Run Compliance Check</span>
          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className="btn-primary flex items-center space-x-2"
          >
            <PlusIcon className="w-5 h-5" />
            <span>Create Policy</span>
          </button>
        </div>
      </div>
      {learningActionKey && (
        <LearningPanel
          action_key={learningActionKey}
          onClose={() => setLearningActionKey(null)}
        />
      )}
      {/* Compliance Summary */}
      {complianceResults && (
        <div className="card bg-primary-50 dark:bg-primary-900/20 border-primary-200 dark:border-primary-800">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-semibold text-primary-900 dark:text-primary-100">
                Compliance Check Complete
              </h3>
              <p className="text-primary-700 dark:text-primary-300 mt-1">
                Checked {complianceResults.policies_checked} policies, found{" "}
                {complianceResults.violations_found} violations
              </p>
            </div>
            <button
              onClick={() => setComplianceResults(null)}
              className="text-primary-600 hover:text-primary-800"
            >
              Dismiss
            </button>
          </div>
          {complianceResults.results.length > 0 && (
            <div className="mt-4 space-y-2">
              {complianceResults.results.map((result, idx) => (
                <div
                  key={idx}
                  className="p-3 bg-white dark:bg-gray-800 rounded-lg"
                >
                  <p className="font-medium text-gray-900 dark:text-white">
                    {result.policy}
                  </p>
                  <p className="text-sm text-danger-600">
                    {result.violations.join(", ")}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {/* Policies List */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {policies.map((policy) => (
          <div
            key={policy.id}
            className="card hover:shadow-md transition-shadow"
          >
            <div className="flex items-start justify-between mb-4">
              <span
                className={`px-2 py-1 rounded-full text-xs font-semibold ${getPolicyTypeColor(policy.policy_type)}`}
              >
                {policy.policy_type}
              </span>
              <span
                className={`px-2 py-1 rounded-full text-xs font-semibold ${
                  policy.auto_remediate
                    ? "bg-success-100 text-success-800"
                    : "bg-gray-100 text-gray-800"
                }`}
              >
                {policy.auto_remediate ? "Auto-remediate" : "Manual"}
              </span>
            </div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
              {policy.name}
            </h3>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              {policy.description}
            </p>
            <div className="p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase font-semibold mb-1">
                Rule
              </p>
              <p className="text-sm text-gray-700 dark:text-gray-300 italic">
                "{policy.policy_rule}"
              </p>
            </div>
            <div className="mt-4 flex items-center justify-between text-sm">
              <span className="text-gray-500 dark:text-gray-400">
                Severity:{" "}
                <span className="font-medium capitalize">
                  {policy.severity}
                </span>
              </span>
              <span
                className={`px-2 py-1 rounded text-xs ${
                  policy.status === "active"
                    ? "bg-success-100 text-success-800"
                    : "bg-gray-100 text-gray-800"
                }`}
              >
                {policy.status}
              </span>
            </div>
          </div>
        ))}
      </div>
      {/* Empty State */}
      {policies.length === 0 && (
        <div className="card text-center py-12">
          <ClipboardDocumentCheckIcon className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
            No policies yet
          </h3>
          <p className="text-gray-500 dark:text-gray-400 mb-4">
            Create your first governance policy to ensure compliance
          </p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="btn-primary"
          >
            Create Policy
          </button>
        </div>
      )}
      {/* Create Policy Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
              Create Governance Policy
            </h2>
            <form onSubmit={handleCreatePolicy} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Policy Name
                </label>
                <input
                  type="text"
                  required
                  className="input-field"
                  value={newPolicy.name}
                  onChange={(e) =>
                    setNewPolicy({ ...newPolicy, name: e.target.value })
                  }
                  placeholder="e.g., Encrypt All Databases"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  className="input-field"
                  rows="2"
                  value={newPolicy.description}
                  onChange={(e) =>
                    setNewPolicy({ ...newPolicy, description: e.target.value })
                  }
                  placeholder="Brief description of the policy"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Policy Rule (Structured)
                </label>
                <textarea
                  required
                  className="input-field"
                  rows="3"
                  value={newPolicy.policy_rule}
                  onChange={(e) =>
                    setNewPolicy({ ...newPolicy, policy_rule: e.target.value })
                  }
                  placeholder="resource_type=database; encryption=required; public_access=deny; tag=Environment:Production"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Use key=value pairs separated by semicolons. This module
                  accepts explicit rules only.
                </p>
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  id="auto_remediate"
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                  checked={newPolicy.auto_remediate}
                  onChange={(e) =>
                    setNewPolicy({
                      ...newPolicy,
                      auto_remediate: e.target.checked,
                    })
                  }
                />
                <label
                  htmlFor="auto_remediate"
                  className="ml-2 text-sm text-gray-700 dark:text-gray-300"
                >
                  Automatically remediate violations
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
