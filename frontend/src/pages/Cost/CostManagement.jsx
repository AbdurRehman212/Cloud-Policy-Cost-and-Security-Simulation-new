import React, { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import axios from "axios";
import {
  fetchCurrentCosts,
  fetchForecast,
  fetchOptimization,
} from "../../store/slices/costSlice";
import LearningPanel from "../../components/Learning/LearningPanel";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import toast from "react-hot-toast";
const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444"];
const API_URL = process.env.REACT_APP_API_URL || "http://localhost:5000/api";
const CostManagement = () => {
  const dispatch = useDispatch();
  const { currentOrganization } = useSelector((state) => state.organization);
  const { token } = useSelector((state) => state.auth);
  const { currentCosts, forecast, recommendations } = useSelector(
    (state) => state.cost,
  );
  const [showBudgetModal, setShowBudgetModal] = useState(false);
  const [learningActionKey, setLearningActionKey] = useState(null);
  const [budgetForm, setBudgetForm] = useState({
    name: "Monthly Cloud Budget",
    amount: "",
    start_date: new Date().toISOString().slice(0, 10),
    period: "monthly",
    alert_threshold_1: 50,
    alert_threshold_2: 80,
    alert_threshold_3: 100,
    auto_shutdown_at_threshold: false,
  });
  useEffect(() => {
    if (currentOrganization) {
      dispatch(fetchCurrentCosts(currentOrganization.id));
      dispatch(fetchForecast({ orgId: currentOrganization.id, days: 30 }));
      dispatch(fetchOptimization(currentOrganization.id));
    }
  }, [dispatch, currentOrganization]);
  const handleCreateBudget = async (event) => {
    event.preventDefault();
    if (!currentOrganization?.id) return;

    try {
      await axios.post(
        `${API_URL}/cost/budgets`,
        {
          organization_id: currentOrganization.id,
          ...budgetForm,
          amount: Number(budgetForm.amount),
          alert_threshold_1: Number(budgetForm.alert_threshold_1),
          alert_threshold_2: Number(budgetForm.alert_threshold_2),
          alert_threshold_3: Number(budgetForm.alert_threshold_3),
        },
        { headers: { Authorization: `Bearer ${token}` } },
      );
      toast.success("Budget created successfully");
      setLearningActionKey("cost_budget_created");
      setShowBudgetModal(false);
      setBudgetForm((previous) => ({
        ...previous,
        amount: "",
      }));
    } catch (error) {
      toast.error(error.response?.data?.error || "Failed to create budget");
    }
  };
  const serviceData = currentCosts?.current_month?.by_service
    ? Object.entries(currentCosts.current_month.by_service).map(
        ([name, value]) => ({
          name: name.toUpperCase(),
          value,
        }),
      )
    : [];
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Cost Management
        </h1>
        <button
          type="button"
          onClick={() => setShowBudgetModal(true)}
          className="btn-primary"
        >
          Create Budget
        </button>
      </div>
      {learningActionKey && (
        <LearningPanel
          action_key={learningActionKey}
          onClose={() => setLearningActionKey(null)}
        />
      )}
      {/* Cost Overview */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="card">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
            Current Month
          </p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">
            ${currentCosts?.current_month?.total?.toFixed(2) || "0.00"}
          </p>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Projected: $
            {currentCosts?.current_month?.projected_month_end?.toFixed(2) ||
              "0.00"}
          </p>
        </div>
        <div className="card">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
            Daily Average
          </p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">
            $
            {currentCosts?.current_month?.total
              ? (currentCosts.current_month.total / 30).toFixed(2)
              : "0.00"}
          </p>
        </div>
        <div className="card">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
            Forecast (30 days)
          </p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">
            ${forecast?.total_predicted?.toFixed(2) || "0.00"}
          </p>
        </div>
        <div className="card">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
            Budget Status
          </p>
          <p className="text-2xl font-bold text-success-600">On Track</p>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            67% of budget used
          </p>
        </div>
      </div>
      {showBudgetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-lg rounded-xl bg-white p-6 dark:bg-gray-800">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">
                  Create Budget
                </h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Set a monthly budget and alert thresholds for this
                  organization.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowBudgetModal(false)}
                className="text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white"
              >
                ×
              </button>
            </div>
            <form className="space-y-4" onSubmit={handleCreateBudget}>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Budget Name
                </label>
                <input
                  className="input-field"
                  value={budgetForm.name}
                  onChange={(event) =>
                    setBudgetForm({ ...budgetForm, name: event.target.value })
                  }
                />
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Amount
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    className="input-field"
                    value={budgetForm.amount}
                    onChange={(event) =>
                      setBudgetForm({
                        ...budgetForm,
                        amount: event.target.value,
                      })
                    }
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Start Date
                  </label>
                  <input
                    type="date"
                    className="input-field"
                    value={budgetForm.start_date}
                    onChange={(event) =>
                      setBudgetForm({
                        ...budgetForm,
                        start_date: event.target.value,
                      })
                    }
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Warning %
                  </label>
                  <input
                    type="number"
                    className="input-field"
                    value={budgetForm.alert_threshold_1}
                    onChange={(event) =>
                      setBudgetForm({
                        ...budgetForm,
                        alert_threshold_1: event.target.value,
                      })
                    }
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Critical %
                  </label>
                  <input
                    type="number"
                    className="input-field"
                    value={budgetForm.alert_threshold_2}
                    onChange={(event) =>
                      setBudgetForm({
                        ...budgetForm,
                        alert_threshold_2: event.target.value,
                      })
                    }
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Exceeded %
                  </label>
                  <input
                    type="number"
                    className="input-field"
                    value={budgetForm.alert_threshold_3}
                    onChange={(event) =>
                      setBudgetForm({
                        ...budgetForm,
                        alert_threshold_3: event.target.value,
                      })
                    }
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                <input
                  type="checkbox"
                  checked={budgetForm.auto_shutdown_at_threshold}
                  onChange={(event) =>
                    setBudgetForm({
                      ...budgetForm,
                      auto_shutdown_at_threshold: event.target.checked,
                    })
                  }
                />
                Auto shutdown at threshold
              </label>
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setShowBudgetModal(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Save Budget
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Cost by Service
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={serviceData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) =>
                  `${name} ${(percent * 100).toFixed(0)}%`
                }
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {serviceData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={COLORS[index % COLORS.length]}
                  />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Daily Cost Trend
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart
              data={
                currentCosts?.current_month?.by_day
                  ? Object.entries(currentCosts.current_month.by_day).map(
                      ([date, cost]) => ({
                        date: date.slice(5),
                        cost,
                      }),
                    )
                  : []
              }
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="cost" fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      {/* Optimization Recommendations */}
      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Cost Optimization Recommendations
        </h3>
        <div className="space-y-4">
          {recommendations.length > 0 ? (
            recommendations.map((item, index) => (
              <div
                key={`${item.instance_id || "recommendation"}-${index}`}
                className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg"
              >
                <div>
                  <p className="font-medium text-gray-900 dark:text-white">
                    {item.instance_id || "Resource optimization"}
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {item.reason || item.recommendation}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold text-success-600">
                    Save ${item.potential_monthly_savings?.toFixed(2) || "0.00"}
                    /mo
                  </p>
                  <button className="text-sm text-primary-600 hover:text-primary-500">
                    Review
                  </button>
                </div>
              </div>
            ))
          ) : (
            <>
              <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                <div>
                  <p className="font-medium text-gray-900 dark:text-white">
                    Right-size underutilized VMs
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    3 VMs running at &lt; 10% CPU
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold text-success-600">
                    Save $450/mo
                  </p>
                  <button className="text-sm text-primary-600 hover:text-primary-500">
                    Apply
                  </button>
                </div>
              </div>
              <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                <div>
                  <p className="font-medium text-gray-900 dark:text-white">
                    Enable Reserved Instances
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    Commit to 1-year term
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold text-success-600">
                    Save $1,200/mo
                  </p>
                  <button className="text-sm text-primary-600 hover:text-primary-500">
                    Apply
                  </button>
                </div>
              </div>
              <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                <div>
                  <p className="font-medium text-gray-900 dark:text-white">
                    Delete unattached storage volumes
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    5 volumes not in use
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold text-success-600">
                    Save $85/mo
                  </p>
                  <button className="text-sm text-primary-600 hover:text-primary-500">
                    Apply
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
export default CostManagement;
