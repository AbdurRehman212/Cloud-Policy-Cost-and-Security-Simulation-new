import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useSelector } from "react-redux";
import { useNavigate, useParams } from "react-router-dom";
import axios from "axios";
import {
  ArrowLeftIcon,
  CheckCircleIcon,
  LightBulbIcon,
  TrophyIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:5000/api";

const ScenarioDetail = () => {
  const { token, user } = useSelector((state) => state.auth);
  const { currentOrganization } = useSelector((state) => state.organization);
  const { id } = useParams();
  const navigate = useNavigate();
  const [scenario, setScenario] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showHint, setShowHint] = useState(false);
  const [validating, setValidating] = useState(false);
  const [showCompletion, setShowCompletion] = useState(false);
  const [visitedPages, setVisitedPages] = useState(() => {
    const saved = localStorage.getItem("scenario:visited_pages");
    return saved ? JSON.parse(saved) : {};
  });
  const authHeaders = useMemo(
    () => (token ? { Authorization: `Bearer ${token}` } : {}),
    [token],
  );

  const orgId = currentOrganization?.id;

  const loadScenario = useCallback(async () => {
    if (!token || !orgId || !id) {
      setScenario(null);
      return;
    }

    setLoading(true);
    try {
      const response = await axios.get(`${API_URL}/scenarios/${id}`, {
        headers: authHeaders,
        params: { organization_id: orgId },
      });
      setScenario(response?.data?.data || null);
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Failed to load scenario",
      );
      setScenario(null);
    } finally {
      setLoading(false);
    }
  }, [authHeaders, id, orgId, token]);

  useEffect(() => {
    loadScenario();
  }, [loadScenario]);

  const trackPageVisit = useCallback((page) => {
    setVisitedPages((prev) => {
      const updated = { ...prev, [page]: true };
      localStorage.setItem("scenario:visited_pages", JSON.stringify(updated));
      return updated;
    });
  }, []);

  const validateStep = useCallback(async () => {
    if (!scenario || !orgId) return;

    const progress = scenario.progress || {};
    const currentStepNumber = (progress.current_step || 0) + 1;
    const step = scenario.steps?.[currentStepNumber - 1];

    if (!step) return;

    setValidating(true);
    try {
      const response = await axios.post(
        `${API_URL}/scenarios/${id}/validate-step`,
        {
          step_id: step.id,
          org_id: orgId,
        },
        { headers: authHeaders },
      );

      const { valid, message } = response?.data?.data || {};

      if (valid) {
        toast.success("Correct! Moving to next step...");

        // Save progress
        await axios.post(
          `${API_URL}/scenarios/${id}/progress`,
          {
            step: currentStepNumber,
            user_id: user?.id,
            org_id: orgId,
          },
          { headers: authHeaders },
        );

        // Reload scenario
        await loadScenario();

        // Check if completed
        const totalSteps = scenario.steps?.length || 0;
        if (currentStepNumber >= totalSteps) {
          // Complete scenario
          await axios.post(
            `${API_URL}/scenarios/${id}/complete`,
            {
              org_id: orgId,
              user_id: user?.id,
              points: scenario.points,
            },
            { headers: authHeaders },
          );
          
          // Award points for scenario completion
          try {
            await axios.post(
              `${API_URL}/progress/award`,
              {
                action: "scenario_completed",
                points: 100,
                scenario_id: id,
                org_id: orgId,
              },
              { headers: authHeaders },
            );
          } catch (awardError) {
            console.error("Failed to award points:", awardError);
          }
          
          setShowCompletion(true);
        }
      } else {
        toast.error(message || "Step not completed yet");
      }
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Validation failed",
      );
    } finally {
      setValidating(false);
    }
  }, [authHeaders, id, orgId, scenario, user?.id, loadScenario]);

  const progress = scenario?.progress || null;
  const totalSteps = scenario?.steps?.length || 0;
  const currentStepNumber = (progress?.current_step || 0) + 1;
  const currentStep = scenario?.steps?.[currentStepNumber - 1] || null;
  const isCompleted = progress?.completed || false;
  const progressPercent = isCompleted
    ? 100
    : totalSteps > 0
      ? ((progress?.current_step || 0) / totalSteps) * 100
      : 0;

  const handleQuickLink = (page) => {
    trackPageVisit(page);
    navigate(`/${page}`);
  };

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center text-gray-500 dark:text-gray-400">
        Loading scenario...
      </div>
    );
  }

  if (!scenario) {
    return (
      <div className="flex h-96 items-center justify-center text-gray-500 dark:text-gray-400">
        Scenario not found
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {showCompletion && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="card max-w-md p-8 text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-success-100 text-success-600 dark:bg-success-900/20">
              <TrophyIcon className="h-8 w-8" />
            </div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
              Lab Complete! 🎉
            </h2>
            <p className="mt-2 text-gray-600 dark:text-gray-400">
              You earned {scenario.points} points
            </p>
            <p className="mt-1 text-sm font-medium text-primary-600 dark:text-primary-400">
              Badge: {scenario.badge}
            </p>
            <div className="mt-6 rounded-lg bg-gray-50 p-4 text-left dark:bg-gray-800">
              <h3 className="font-semibold text-gray-900 dark:text-white">
                What you learned
              </h3>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                {scenario.description}
              </p>
            </div>
            <div className="mt-6 flex gap-3">
              <button
                type="button"
                onClick={() => setShowCompletion(false)}
                className="flex-1 rounded-xl bg-gray-200 px-4 py-3 text-sm font-semibold text-gray-900 transition-colors hover:bg-gray-300 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600"
              >
                Review
              </button>
              <button
                type="button"
                onClick={() => navigate("/scenarios")}
                className="flex-1 rounded-xl bg-primary-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-primary-500"
              >
                Next Lab
              </button>
            </div>
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => navigate("/scenarios")}
        className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white"
      >
        <ArrowLeftIcon className="h-4 w-4" />
        Back to Labs
      </button>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        {/* Left Column - Steps */}
        <div className="lg:col-span-1 space-y-4">
          <div className="card">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              {scenario.title}
            </h2>
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              {scenario.description}
            </p>
          </div>

          <div className="card">
            <div className="mb-4">
              <div className="flex items-center justify-between text-sm font-medium text-gray-700 dark:text-gray-300">
                <span>
                  Step {isCompleted ? totalSteps : currentStepNumber} of{" "}
                  {totalSteps}
                </span>
                <span>{Math.round(progressPercent)}%</span>
              </div>
              <div className="mt-2 h-2 w-full rounded-full bg-gray-200 dark:bg-gray-700">
                <div
                  className="h-2 rounded-full bg-primary-600 transition-all"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>

            <div className="space-y-2">
              {scenario.steps?.map((step, index) => {
                const stepNumber = index + 1;
                const isCurrent = stepNumber === currentStepNumber;
                const isPast = stepNumber < currentStepNumber;

                return (
                  <div
                    key={step.id}
                    className={`flex items-start gap-3 rounded-lg p-3 ${
                      isCurrent
                        ? "bg-primary-50 border border-primary-200 dark:bg-primary-900/20 dark:border-primary-800"
                        : isPast
                          ? "bg-success-50 border border-success-200 dark:bg-success-900/20 dark:border-success-800"
                          : "bg-gray-50 dark:bg-gray-800"
                    }`}
                  >
                    <div
                      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                        isPast
                          ? "bg-success-600 text-white"
                          : isCurrent
                            ? "bg-primary-600 text-white"
                            : "bg-gray-300 text-gray-700 dark:bg-gray-600 dark:text-gray-300"
                      }`}
                    >
                      {isPast ? (
                        <CheckCircleIcon className="h-4 w-4" />
                      ) : (
                        stepNumber
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                        {step.title}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="card">
            <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
              <TrophyIcon className="h-5 w-5 text-primary-600" />
              <span className="font-medium">{scenario.points} points</span>
            </div>
            <div className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              Badge: {scenario.badge}
            </div>
          </div>
        </div>

        {/* Middle Column - Main Lab Area */}
        <div className="lg:col-span-2 space-y-4">
          {isCompleted ? (
            <div className="card">
              <div className="rounded-2xl border border-success-200 bg-success-50 p-6 dark:border-success-900/30 dark:bg-success-900/10">
                <div className="flex items-start gap-4">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-success-100 text-success-600 dark:bg-success-900/20">
                    <CheckCircleIcon className="h-6 w-6" />
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold text-success-900 dark:text-success-100">
                      Lab Complete! 🎉
                    </h3>
                    <p className="mt-2 text-success-800 dark:text-success-200">
                      You've successfully completed all steps of this lab.
                    </p>
                    <div className="mt-4 flex gap-3">
                      <button
                        type="button"
                        onClick={() => navigate("/scenarios")}
                        className="rounded-xl bg-primary-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary-500"
                      >
                        Next Lab
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <>
              <div className="card">
                <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
                  {currentStep?.title}
                </h2>
                <p className="mt-4 text-lg text-gray-700 dark:text-gray-300">
                  {currentStep?.instruction}
                </p>

                <button
                  type="button"
                  onClick={() => setShowHint((prev) => !prev)}
                  className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-primary-600 hover:text-primary-500"
                >
                  <LightBulbIcon className="h-4 w-4" />
                  {showHint ? "Hide Hint" : "Show Hint"}
                </button>

                {showHint && (
                  <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900/30 dark:bg-amber-900/10 dark:text-amber-200">
                    <p className="font-semibold">Hint</p>
                    <p className="mt-1">{currentStep?.hint}</p>
                  </div>
                )}
              </div>

              <div className="card border-l-4 border-l-blue-500">
                <p className="text-sm font-semibold uppercase tracking-wide text-blue-700 dark:text-blue-300">
                  In real AWS...
                </p>
                <p className="mt-2 text-sm text-gray-700 dark:text-gray-300">
                  {currentStep?.aws_context}
                </p>
              </div>

              <button
                type="button"
                onClick={validateStep}
                disabled={validating}
                className="w-full rounded-xl bg-primary-600 px-6 py-4 text-base font-semibold text-white transition-colors hover:bg-primary-500 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {validating ? "Validating..." : "Validate Step"}
              </button>
            </>
          )}
        </div>

        {/* Right Column - AWS Context */}
        <div className="lg:col-span-1 space-y-4">
          <div className="card">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              AWS Context
            </h3>
            <p className="mt-3 text-sm text-gray-700 dark:text-gray-300">
              {currentStep?.aws_context}
            </p>
          </div>

          <div className="card">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              Quick Links
            </h3>
            <div className="mt-3 space-y-2">
              <button
                type="button"
                onClick={() => handleQuickLink("resources")}
                className="w-full rounded-lg bg-gray-100 px-3 py-2 text-left text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                Go to Resources
              </button>
              <button
                type="button"
                onClick={() => handleQuickLink("security")}
                className="w-full rounded-lg bg-gray-100 px-3 py-2 text-left text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                Go to Security
              </button>
              <button
                type="button"
                onClick={() => handleQuickLink("cost")}
                className="w-full rounded-lg bg-gray-100 px-3 py-2 text-left text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                Go to Cost
              </button>
            </div>
          </div>

          <div className="card">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              Progress Tracker
            </h3>
            <div className="mt-3 space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-gray-600 dark:text-gray-400">
                  Resources visited
                </span>
                <span
                  className={`font-medium ${
                    visitedPages.resources
                      ? "text-success-600"
                      : "text-gray-400"
                  }`}
                >
                  {visitedPages.resources ? "✓" : "○"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-600 dark:text-gray-400">
                  Security visited
                </span>
                <span
                  className={`font-medium ${
                    visitedPages.security
                      ? "text-success-600"
                      : "text-gray-400"
                  }`}
                >
                  {visitedPages.security ? "✓" : "○"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-600 dark:text-gray-400">
                  Cost visited
                </span>
                <span
                  className={`font-medium ${
                    visitedPages.cost ? "text-success-600" : "text-gray-400"
                  }`}
                >
                  {visitedPages.cost ? "✓" : "○"}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ScenarioDetail;
