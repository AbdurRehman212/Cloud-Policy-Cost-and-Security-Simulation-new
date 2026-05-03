import React, { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import axios from "axios";
import { io } from "socket.io-client";
import { fetchThreats, simulateAttack } from "../../store/slices/securitySlice";
import LearningPanel from "../../components/Learning/LearningPanel";
import {
  ShieldCheckIcon,
  ExclamationTriangleIcon,
  BugAntIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:5000/api";
const Security = () => {
  const dispatch = useDispatch();
  const { currentOrganization } = useSelector((state) => state.organization);
  const { threats } = useSelector((state) => state.security);
  const activeOrgId = currentOrganization?.id;
  const [showSimulateModal, setShowSimulateModal] = useState(false);
  const [attackType, setAttackType] = useState("ddos");
  const [learningActionKey, setLearningActionKey] = useState(null);
  const [resolvingThreatId, setResolvingThreatId] = useState(null);
  const socketRef = useRef(null);

  useEffect(() => {
    if (activeOrgId) {
      dispatch(fetchThreats(activeOrgId));
    }
  }, [dispatch, activeOrgId]);

  useEffect(() => {
    if (threats.length > 0) {
      localStorage.setItem("scenario:threat_viewed", "true");
    }
  }, [threats]);

  // Listen for real-time threats:update socket events
  useEffect(() => {
    if (!activeOrgId) return;
    const socket = io("http://localhost:5000/metrics", {
      transports: ["websocket"],
      reconnectionAttempts: 5,
    });
    socketRef.current = socket;
    socket.on("connect", () => {
      socket.emit("join_room", { org_id: activeOrgId });
    });
    socket.on("threats:update", () => {
      dispatch(fetchThreats(activeOrgId));
    });
    return () => socket.disconnect();
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
        attackType === "brute_force" ? "brute_force_attack" : "ddos_attack",
      );
      
      // Award points for attack simulation
      try {
        await axios.post(
          `${API_URL}/progress/award`,
          {
            action: "attack_simulated",
            points: 20,
            org_id: currentOrganization?.id,
          },
          {
            headers: {
              Authorization: `Bearer ${localStorage.getItem("token") || ""}`,
            },
          },
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
      await axios.post(
        `${API_URL}/security/threats/${threatId}/resolve`,
        {},
        {
          headers: {
            Authorization: `Bearer ${localStorage.getItem("token") || ""}`,
          },
        },
      );
      localStorage.setItem("scenario:threat_resolved", "true");
      toast.success("Threat resolved");
      dispatch(fetchThreats(activeOrgId));
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
        <button
          onClick={() => setShowSimulateModal(true)}
          className="btn-secondary flex items-center space-x-2"
        >
          <BugAntIcon className="w-5 h-5" />
          <span>Simulate Attack</span>
        </button>
      </div>
      {/* Security Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                Security Score
              </p>
              <p className="text-3xl font-bold text-success-600">94/100</p>
            </div>
            <ShieldCheckIcon className="w-12 h-12 text-success-500" />
          </div>
        </div>
        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                Active Threats
              </p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">
                {threats.length}
              </p>
            </div>
            <ExclamationTriangleIcon className="w-12 h-12 text-warning-500" />
          </div>
        </div>
        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                Protected Resources
              </p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">
                100%
              </p>
            </div>
            <ShieldCheckIcon className="w-12 h-12 text-primary-500" />
          </div>
        </div>
      </div>
      {learningActionKey && (
        <LearningPanel
          action_key={learningActionKey}
          onClose={() => setLearningActionKey(null)}
        />
      )}
      {/* Threats Table */}
      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Detected Threats
        </h3>
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
                    {threat.status !== "resolved" &&
                      (currentOrganization?.my_role === "admin" ||
                        currentOrganization?.my_role === "owner") && (
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
                    No threats detected. Your infrastructure is secure.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {/* Simulate Attack Modal */}
      {showSimulateModal && (
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
