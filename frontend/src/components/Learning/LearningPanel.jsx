import React, { useEffect, useState } from "react";
import axios from "axios";
import {
  ArrowRightIcon,
  ExclamationTriangleIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:5000/api";

const difficultyStyles = {
  beginner:
    "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
  intermediate:
    "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  advanced: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
};

const LearningPanel = ({ action_key, onClose }) => {
  const [content, setContent] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (!action_key) return undefined;

    let cancelled = false;
    setIsVisible(false);

    const loadContent = async () => {
      setLoading(true);
      setError("");
      try {
        const response = await axios.get(
          `${API_URL}/learning/content/${action_key}`,
        );
        if (!cancelled) {
          setContent(response.data?.data || null);
        }
      } catch (requestError) {
        if (!cancelled) {
          setContent(null);
          setError(
            requestError.response?.data?.error?.message ||
              "Learning content unavailable.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    loadContent();
    const timer = window.setTimeout(() => setIsVisible(true), 20);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [action_key]);

  if (!action_key) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-label="Close learning panel"
      />
      <aside
        className={`absolute right-0 top-0 h-full w-full max-w-xl bg-white shadow-2xl transition-transform duration-300 ease-out dark:bg-gray-900 ${
          isVisible ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-start justify-between border-b border-gray-200 px-6 py-5 dark:border-gray-800">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-primary-600 dark:text-primary-400">
                What You Just Learned
              </p>
              <h2 className="mt-1 text-2xl font-bold text-gray-900 dark:text-white">
                Learning Overlay
              </h2>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-full p-2 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-white"
              aria-label="Close"
            >
              <XMarkIcon className="h-5 w-5" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-6 py-6">
            {loading && (
              <div className="rounded-xl border border-dashed border-gray-300 p-6 text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400">
                Loading learning content...
              </div>
            )}

            {!loading && error && (
              <div className="rounded-xl border border-warning-200 bg-warning-50 p-4 text-sm text-warning-800 dark:border-warning-800 dark:bg-warning-900/20 dark:text-warning-100">
                {error}
              </div>
            )}

            {!loading && content && (
              <div className="space-y-5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-black px-3 py-1 text-xs font-semibold text-white">
                    AWS
                  </span>
                  <span className="rounded-full bg-blue-600 px-3 py-1 text-xs font-semibold text-white">
                    Azure
                  </span>
                  <span
                    className={`rounded-full px-3 py-1 text-xs font-semibold ${difficultyStyles[content.difficulty] || difficultyStyles.beginner}`}
                  >
                    {String(content.difficulty || "beginner").replace(
                      /^\w/,
                      (char) => char.toUpperCase(),
                    )}
                  </span>
                </div>

                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-800 dark:bg-gray-800/60">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    AWS Equivalent
                  </p>
                  <p className="mt-1 text-base font-semibold text-gray-900 dark:text-white">
                    {content.aws_equivalent}
                  </p>
                  <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    Azure Equivalent
                  </p>
                  <p className="mt-1 text-base font-semibold text-gray-900 dark:text-white">
                    {content.azure_equivalent}
                  </p>
                </div>

                <div>
                  <p className="text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    What You Just Did
                  </p>
                  <p className="mt-2 text-gray-700 dark:text-gray-300">
                    {content.what_you_just_did}
                  </p>
                </div>

                <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-900/20">
                  <p className="text-sm font-semibold uppercase tracking-wide text-blue-700 dark:text-blue-300">
                    Key Concept
                  </p>
                  <p className="mt-2 text-blue-950 dark:text-blue-100">
                    {content.key_concept}
                  </p>
                </div>

                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-900/20">
                  <div className="flex items-center gap-2 text-amber-700 dark:text-amber-300">
                    <ExclamationTriangleIcon className="h-5 w-5" />
                    <p className="text-sm font-semibold uppercase tracking-wide">
                      Best Practice
                    </p>
                  </div>
                  <p className="mt-2 text-amber-950 dark:text-amber-100">
                    {content.best_practice}
                  </p>
                </div>

                <div className="rounded-2xl border border-gray-200 p-4 dark:border-gray-800">
                  <div className="flex items-center gap-2 text-primary-600 dark:text-primary-400">
                    <ArrowRightIcon className="h-5 w-5" />
                    <p className="text-sm font-semibold uppercase tracking-wide">
                      Next Step
                    </p>
                  </div>
                  <p className="mt-2 text-gray-700 dark:text-gray-300">
                    {content.next_step}
                  </p>
                </div>

                <div className="flex flex-wrap gap-2 pt-1">
                  <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                    {content.certification_topic}
                  </span>
                  <span className="rounded-full bg-primary-100 px-3 py-1 text-xs font-medium text-primary-700 dark:bg-primary-900/30 dark:text-primary-300">
                    Relevant for AWS CLF-C02
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
};

export default LearningPanel;
