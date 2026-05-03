import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useSelector } from "react-redux";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import {
  AcademicCapIcon,
  ClockIcon,
  TrophyIcon,
  PlayIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:5000/api";

const difficultyStyles = {
  beginner:
    "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-300",
  intermediate:
    "bg-amber-100 text-amber-800 dark:bg-amber-900/20 dark:text-amber-300",
  advanced: "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-300",
};

const Scenarios = () => {
  const { token } = useSelector((state) => state.auth);
  const { currentOrganization } = useSelector((state) => state.organization);
  const [scenarios, setScenarios] = useState([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const authHeaders = useMemo(
    () => (token ? { Authorization: `Bearer ${token}` } : {}),
    [token],
  );

  const orgId = currentOrganization?.id;

  const loadScenarios = useCallback(async () => {
    if (!token || !orgId) {
      setScenarios([]);
      return;
    }

    setLoading(true);
    try {
      const response = await axios.get(`${API_URL}/scenarios`, {
        headers: authHeaders,
        params: { organization_id: orgId },
      });
      setScenarios(
        Array.isArray(response?.data?.data) ? response.data.data : [],
      );
    } catch (error) {
      setScenarios([]);
      toast.error(
        error?.response?.data?.error?.message || "Failed to load scenarios",
      );
    } finally {
      setLoading(false);
    }
  }, [authHeaders, orgId, token]);

  useEffect(() => {
    loadScenarios();
  }, [loadScenarios]);

  const filteredScenarios = useMemo(() => {
    if (filter === "all") return scenarios;
    return scenarios.filter(
      (scenario) => (scenario.difficulty || "").toLowerCase() === filter,
    );
  }, [filter, scenarios]);

  return (
    <div className="space-y-6">
      <div className="rounded-3xl bg-gradient-to-r from-slate-900 via-slate-800 to-blue-900 px-6 py-8 text-white shadow-lg">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-white/80">
              <AcademicCapIcon className="h-4 w-4" />
              Cloud Learning Labs
            </p>
            <h1 className="mt-3 text-3xl font-bold">Cloud Learning Labs</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-200">
              Practice real cloud scenarios in a safe environment. No billing risk.
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm text-slate-200">
            <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1">
              <ClockIcon className="h-4 w-4" />
              {scenarios.length} Labs
            </span>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {["all", "beginner", "intermediate"].map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setFilter(item)}
            className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
              filter === item
                ? "bg-primary-600 text-white"
                : "bg-white text-gray-700 border border-gray-200 hover:border-primary-300 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700"
            }`}
          >
            {item === "all"
              ? "All"
              : item.charAt(0).toUpperCase() + item.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="card flex min-h-48 items-center justify-center text-gray-500 dark:text-gray-400">
          Loading scenarios...
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3">
          {filteredScenarios.map((scenario) => (
            <div key={scenario.id} className="card flex flex-col gap-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1">
                  <h3 className="text-lg font-bold text-gray-900 dark:text-white">
                    {scenario.title}
                  </h3>
                  <p className="mt-2 text-sm text-gray-500 dark:text-gray-400 line-clamp-2">
                    {scenario.description}
                  </p>
                </div>
                <span
                  className={`rounded-full px-3 py-1 text-xs font-semibold ${difficultyStyles[scenario.difficulty] || "bg-gray-100 text-gray-800"}`}
                >
                  {scenario.difficulty}
                </span>
              </div>

              <div className="flex flex-wrap gap-2">
                {(scenario.aws_services || []).map((service) => (
                  <span
                    key={service}
                    className="rounded-full bg-gray-100 px-2 py-1 text-xs font-medium text-gray-700 dark:bg-gray-700 dark:text-gray-300"
                  >
                    {service}
                  </span>
                ))}
              </div>

              <div className="flex items-center justify-between gap-3 text-sm text-gray-500 dark:text-gray-400">
                <span className="inline-flex items-center gap-1">
                  <ClockIcon className="h-4 w-4" />
                  {scenario.duration_minutes} min
                </span>
                <span className="inline-flex items-center gap-1 rounded-full bg-primary-50 px-2 py-1 text-primary-700 dark:bg-primary-900/20 dark:text-primary-300">
                  <TrophyIcon className="h-4 w-4" />
                  {scenario.points} pts
                </span>
              </div>

              <button
                type="button"
                onClick={() => navigate(`/scenarios/${scenario.id}`)}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-primary-500"
              >
                <PlayIcon className="h-4 w-4" />
                Start Lab
              </button>
            </div>
          ))}

          {filteredScenarios.length === 0 && (
            <div className="col-span-full card py-16 text-center text-gray-500 dark:text-gray-400">
              No scenarios match this filter.
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default Scenarios;
