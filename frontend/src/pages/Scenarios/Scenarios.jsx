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

const API_URL = process.env.REACT_APP_API_URL || "/api";

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
  const [learningProfile, setLearningProfile] = useState(null);
  const [selectedLevel, setSelectedLevel] = useState("beginner");
  const [loading, setLoading] = useState(false);
  // Track which scenario IDs currently have a simulation running
  const [runningScenarios, setRunningScenarios] = useState({});
  const navigate = useNavigate();
  const authHeaders = useMemo(
    () => (token ? { Authorization: `Bearer ${token}` } : {}),
    [token],
  );

  const orgId = currentOrganization?.id;

  const loadScenarios = useCallback(async (overrideLevel = null) => {
    if (!token || !orgId) {
      setScenarios([]);
      setLearningProfile(null);
      return;
    }

    const effectiveLevel = overrideLevel || selectedLevel;

    setLoading(true);
    try {
      const response = await axios.get(`${API_URL}/scenarios`, {
        headers: authHeaders,
        params: { organization_id: orgId, level: effectiveLevel },
      });
      setScenarios(
        Array.isArray(response?.data?.data) ? response.data.data : [],
      );
      const profileResponse = await axios.get(`${API_URL}/learning/experience`, {
        headers: authHeaders,
        params: { organization_id: orgId, level: effectiveLevel },
      });
      const profile = profileResponse?.data?.data || null;
      setLearningProfile(profile);
      setSelectedLevel(profile?.selected_level || profile?.learning_track || effectiveLevel);
    } catch (error) {
      setScenarios([]);
      setLearningProfile(null);
      toast.error(
        error?.response?.data?.error?.message || "Failed to load scenarios",
      );
    } finally {
      setLoading(false);
    }
  }, [authHeaders, orgId, selectedLevel, token]);

  useEffect(() => {
    loadScenarios();
  }, [loadScenarios]);

  const filteredScenarios = useMemo(() => {
    return scenarios;
  }, [scenarios]);

  const handleSelectLevel = useCallback(async (level) => {
    if (!token || !orgId) return;
    setSelectedLevel(level);
    try {
      await axios.post(
        `${API_URL}/learning/level`,
        { organization_id: orgId, level },
        { headers: authHeaders },
      );
      await loadScenarios(level);
    } catch (error) {
      toast.error(error?.response?.data?.error?.message || "Failed to update learning level");
    }
  }, [authHeaders, loadScenarios, orgId, token]);

  // POST /scenarios/<id>/run — starts the engine-driven simulation
  const handleStartSimulation = useCallback(async (scenario) => {
    if (!token || !orgId || scenario.learning_lock?.locked) return;
    const sid = scenario.id;
    setRunningScenarios((prev) => ({ ...prev, [sid]: true }));
    try {
      await axios.post(
        `${API_URL}/scenarios/${sid}/run`,
        { org_id: orgId, tick_delay_seconds: 0.4 },
        { headers: authHeaders },
      );
      toast.success(`Simulation started for "${scenario.title}"`);
      // Navigate to detail page so the user can watch the live progress
      navigate(`/scenarios/${sid}`);
    } catch (err) {
      const code = err?.response?.data?.error?.code;
      if (code === "scenario_already_running") {
        toast("Simulation already running — navigating to detail page.");
        navigate(`/scenarios/${sid}`);
      } else {
        toast.error(err?.response?.data?.error?.message || "Failed to start simulation");
        setRunningScenarios((prev) => ({ ...prev, [sid]: false }));
      }
    }
  }, [authHeaders, navigate, orgId, token]);

  return (
    <div className="space-y-6">
      <div className="rounded-3xl bg-gradient-to-r from-slate-900 via-slate-800 to-blue-900 px-6 py-8 text-white shadow-lg">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-white/80">
              <AcademicCapIcon className="h-4 w-4" />
              Scenario-based learning
            </p>
            <h1 className="mt-3 text-3xl font-bold">Learn cloud by solving real problems</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-200">
              Follow the loop: user → scenario → action → simulation → result → explanation.
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm text-slate-200">
            <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1">
              <ClockIcon className="h-4 w-4" />
              {scenarios.length} Modules
            </span>
            {learningProfile?.role_info?.title && (
              <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1">
                <TrophyIcon className="h-4 w-4" />
                {learningProfile.role_info.title}
              </span>
            )}
            {learningProfile?.level?.title && (
              <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1">
                <TrophyIcon className="h-4 w-4" />
                {learningProfile.level.title}
              </span>
            )}
          </div>
        </div>
      </div>

      {learningProfile?.learning_loop && (
        <div className="card border-l-4 border-primary-500">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-3xl">
              <p className="text-xs font-semibold uppercase tracking-wide text-primary-600 dark:text-primary-400">
                Learning path
              </p>
              <h2 className="mt-2 text-xl font-bold text-gray-900 dark:text-white">
                {learningProfile.recommended_scenario?.title || "Choose a module to start"}
              </h2>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
                Role: {learningProfile.role_info?.title || learningProfile.role || "Student"} • Stage: {learningProfile.level?.title || "Beginner"}
              </p>
              <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
                {learningProfile.learning_loop.explanation?.why_this_changes_metrics || learningProfile.learning_loop.explanation?.why}
              </p>
            </div>
            <div className="grid gap-2 text-sm text-gray-600 dark:text-gray-300 lg:min-w-80">
              {[
                ["User", learningProfile.learning_loop.user],
                ["Scenario", learningProfile.learning_loop.scenario],
                ["Action", learningProfile.learning_loop.action],
                ["Simulation", learningProfile.learning_loop.simulation],
                ["Result", learningProfile.learning_loop.result],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl bg-gray-50 px-3 py-2 dark:bg-gray-800">
                  <strong>{label}:</strong> {value}
                </div>
              ))}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {learningProfile.progression_path?.map((item) => (
              <span key={item.level} className="rounded-full bg-primary-50 px-3 py-1 text-xs font-semibold text-primary-700 dark:bg-primary-900/20 dark:text-primary-300">
                {item.title}
              </span>
            ))}
          </div>
          {learningProfile.workload_patterns && (
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl bg-gray-50 p-3 text-sm text-gray-700 dark:bg-gray-800 dark:text-gray-200">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Spikes</p>
                <p className="mt-1">Peak CPU {learningProfile.workload_patterns.spikes?.peak_cpu ?? 0}%</p>
              </div>
              <div className="rounded-2xl bg-gray-50 p-3 text-sm text-gray-700 dark:bg-gray-800 dark:text-gray-200">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Seasonal traffic</p>
                <p className="mt-1">{learningProfile.workload_patterns.seasonal?.peak_window?.length || 0} peak samples</p>
              </div>
              <div className="rounded-2xl bg-gray-50 p-3 text-sm text-gray-700 dark:bg-gray-800 dark:text-gray-200">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Failures</p>
                <p className="mt-1">{learningProfile.workload_patterns.failures?.length || 0} failure signals</p>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {learningProfile?.level_options?.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => handleSelectLevel(item.id)}
            className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
              selectedLevel === item.id
                ? "bg-primary-600 text-white"
                : "bg-white text-gray-700 border border-gray-200 hover:border-primary-300 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700"
            }`}
          >
            {item.title}
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
                  <p className="text-xs font-semibold uppercase tracking-wide text-primary-600 dark:text-primary-400">
                    {scenario.module || "Learning module"}
                  </p>
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

              {scenario.learning_lock?.locked && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/40 dark:bg-amber-900/10 dark:text-amber-100">
                  <p className="font-semibold">Locked progression</p>
                  <p className="mt-1">{scenario.learning_lock.reason || "Complete the current module first."}</p>
                </div>
              )}

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

              <div className="rounded-xl bg-slate-50 p-3 text-sm text-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
                <p className="font-semibold text-slate-900 dark:text-white">Why this matters</p>
                <p className="mt-1">{scenario.cause_effect?.why}</p>
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

              <p className="text-sm text-gray-600 dark:text-gray-300">
                {scenario.learning_objective}
              </p>

              <button
                type="button"
                onClick={() => handleStartSimulation(scenario)}
                disabled={scenario.learning_lock?.locked || runningScenarios[scenario.id]}
                className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                  scenario.learning_lock?.locked
                    ? "bg-gray-400"
                    : runningScenarios[scenario.id]
                    ? "bg-primary-400"
                    : "bg-primary-600 hover:bg-primary-500"
                }`}
              >
                <PlayIcon className="h-4 w-4" />
                {scenario.learning_lock?.locked
                  ? "Locked"
                  : runningScenarios[scenario.id]
                  ? "Starting…"
                  : scenario.progress?.completed
                  ? "Replay"
                  : (scenario.progress?.current_step || 0) > 0
                  ? "Continue"
                  : "Start Module"}
              </button>
            </div>
          ))}

          {!loading && filteredScenarios.length === 0 && (
            <div className="col-span-full card py-16 text-center text-gray-500 dark:text-gray-400">
              No scenarios available yet. Try a different learning level.
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default Scenarios;
