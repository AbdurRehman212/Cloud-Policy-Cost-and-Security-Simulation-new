import React, { useEffect, useState } from "react";
import { useSelector } from "react-redux";
import { TrophyIcon } from "@heroicons/react/24/outline";
import axios from "axios";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:5000/api";

const UserProgressBar = () => {
  const { token } = useSelector((state) => state.auth);
  const { currentOrganization } = useSelector((state) => state.organization);
  const [progress, setProgress] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token || !currentOrganization?.id) {
      setProgress(null);
      setLoading(false);
      return;
    }

    const loadProgress = async () => {
      try {
        const response = await axios.get(`${API_URL}/progress`, {
          headers: { Authorization: `Bearer ${token}` },
          params: { organization_id: currentOrganization.id },
        });
        setProgress(response?.data?.data || null);
      } catch (error) {
        setProgress(null);
      } finally {
        setLoading(false);
      }
    };

    loadProgress();
  }, [token, currentOrganization?.id]);

  if (loading || !progress) {
    return null;
  }

  const { level, level_title, xp_for_current_level, xp_to_next_level } = progress;
  const xpForLevel = xp_for_current_level || 0;
  const xpNeeded = xp_to_next_level || 100;
  const xpProgress = Math.min(100, (xpForLevel / xpNeeded) * 100);

  return (
    <div className="flex items-center gap-3 rounded-lg bg-gray-100 dark:bg-gray-700 px-3 py-2">
      <TrophyIcon className="h-5 w-5 text-amber-500" />
      <div className="flex flex-col">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-900 dark:text-white">
            Level {level}
          </span>
          <span className="text-xs text-gray-600 dark:text-gray-400">
            {level_title}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-24 rounded-full bg-gray-300 dark:bg-gray-600">
            <div
              className="h-1.5 rounded-full bg-primary-500 transition-all"
              style={{ width: `${xpProgress}%` }}
            />
          </div>
          <span className="text-xs text-gray-600 dark:text-gray-400">
            {xpForLevel}/{xpNeeded} XP
          </span>
        </div>
      </div>
    </div>
  );
};

export default UserProgressBar;
