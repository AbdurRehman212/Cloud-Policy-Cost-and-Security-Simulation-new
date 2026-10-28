import React, { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import {
  fetchCurrentCosts,
  fetchForecast,
  fetchOptimization,
} from "../../store/slices/costSlice";
import LearningPanel from "../../components/Learning/LearningPanel";
import apiClient from "../../services/api";
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

const formatMoney = (value) => `$${Number(value || 0).toFixed(2)}`;

const CostManagement = () => {
  const dispatch = useDispatch();
  const { currentOrganization } = useSelector((state) => state.organization);
  const { currentCosts, forecast, recommendations, loading } = useSelector(
    (state) => state.cost,
  );
  const canManageBudgets =
    currentOrganization?.my_role === "admin" ||
    currentOrganization?.my_role === "owner";
  const [showBudgetModal, setShowBudgetModal] = useState(false);
  const [editingBudgetId, setEditingBudgetId] = useState(null);
  const [learningActionKey, setLearningActionKey] = useState(null);
  const [resourceCosts, setResourceCosts] = useState(null);
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
      apiClient
        .get("/cost/summary", {
          params: { organization_id: currentOrganization.id },
        })
        .then((res) => setResourceCosts(res.data?.by_resource || []))
        .catch(() => setResourceCosts([]));
    }
  }, [dispatch, currentOrganization]);
  const handleCreateBudget = async (event) => {
    event.preventDefault();
    if (!currentOrganization?.id) return;

    const payload = {
      organization_id: currentOrganization.id,
      ...budgetForm,
      amount: Number(budgetForm.amount),
      alert_threshold_1: Number(budgetForm.alert_threshold_1),
      alert_threshold_2: Number(budgetForm.alert_threshold_2),
      alert_threshold_3: Number(budgetForm.alert_threshold_3),
    };
    if (!(payload.amount > 0)) {
      toast.error("Budget amount must be greater than 0");
      return;
    }
    if (
      !(payload.alert_threshold_1 > 0 &&
        payload.alert_threshold_1 <= payload.alert_threshold_2 &&
        payload.alert_threshold_2 <= payload.alert_threshold_3)
    ) {
      toast.error("Alert thresholds must be positive and in ascending order");
      return;
    }

    try {
      if (editingBudgetId) {
        await apiClient.put(`/cost/budgets/${editingBudgetId}`, payload);
        toast.success("Budget updated");
      } else {
        await apiClient.post("/cost/budgets", payload);
        toast.success("Budget created successfully");
        setLearningActionKey("cost_budget_created");
      }
      closeBudgetModal();
      dispatch(fetchCurrentCosts(currentOrganization.id));
    } catch (error) {
      toast.error(
        error.response?.data?.error ||
          (editingBudgetId ? "Failed to update budget" : "Failed to create budget"),
      );
    }
  };
  const closeBudgetModal = () => {
    setShowBudgetModal(false);
    setEditingBudgetId(null);
    setBudgetForm((previous) => ({ ...previous, amount: "" }));
  };
  const openEditBudget = (budget) => {
    setEditingBudgetId(budget.id);
    setBudgetForm({
      name: budget.name,
      amount: String(budget.amount),
      start_date: budget.start_date || new Date().toISOString().slice(0, 10),
      period: budget.period || "monthly",
      alert_threshold_1: budget.alert_thresholds?.warning ?? 50,
      alert_threshold_2: budget.alert_thresholds?.critical ?? 80,
      alert_threshold_3: budget.alert_thresholds?.exceeded ?? 100,
      auto_shutdown_at_threshold: false,
    });
    setShowBudgetModal(true);
  };
  const deleteBudget = async (budget) => {
    if (!window.confirm(`Delete budget "${budget.name}"?`)) return;
    try {
      await apiClient.delete(`/cost/budgets/${budget.id}`);
      toast.success("Budget deleted");
      dispatch(fetchCurrentCosts(currentOrganization.id));
    } catch (error) {
      toast.error(error.response?.data?.error || "Failed to delete budget");
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
  const dailyTrendData = currentCosts?.current_month?.by_day
    ? Object.entries(currentCosts.current_month.by_day).map(([date, cost]) => ({
        date: date.slice(5),
        cost,
      }))
    : [];
  const costSummary = currentCosts?.costs || null;
  const activeBudgets = costSummary?.budgets || [];
  const primaryBudget = activeBudgets[0] || null;
  const trackedDays = dailyTrendData.length;
  const hasCostData = Boolean(serviceData.length || dailyTrendData.length);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Cost Management
        </h1>
        {canManageBudgets ? (
          <button
            type="button"
            onClick={() => setShowBudgetModal(true)}
            className="btn-primary"
            data-tour="create-budget"
          >
            Create Budget
          </button>
        ) : (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Only admins and owners can create or change budgets.
          </p>
        )}
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
            {formatMoney(currentCosts?.current_month?.total)}
          </p>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Projected: {formatMoney(currentCosts?.current_month?.projected_month_end)}
          </p>
        </div>
        <div className="card">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
            Tracked Days
          </p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">
            {trackedDays}
          </p>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Days with persisted cost activity this month
          </p>
        </div>
        <div className="card" data-tour="cost-forecast">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
            Forecast (30 days, estimate)
          </p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">
            ${forecast?.total_predicted?.toFixed(2) || "0.00"}
          </p>
          {forecast?.note && (
            <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
              {forecast.note}
            </p>
          )}
          {forecast && !forecast.note && (
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Linear trend over {forecast.history_days} day(s) of simulated cost history.
            </p>
          )}
        </div>
        <div className="card">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
            Budget Status
          </p>
          {primaryBudget ? (
            <>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {primaryBudget.alert_level === "critical"
                  ? "Exceeded"
                  : primaryBudget.alert_level === "warning"
                    ? "Warning"
                    : "On Track"}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                {primaryBudget.name}: {Number(primaryBudget.percentage_used || 0).toFixed(1)}% used
              </p>
            </>
          ) : (
            <>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                No Budget
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Create a persisted budget to track spend against limits
              </p>
            </>
          )}
        </div>
      </div>
      {showBudgetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-lg rounded-xl bg-white p-6 dark:bg-gray-800">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">
                  {editingBudgetId ? "Edit Budget" : "Create Budget"}
                </h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Set a monthly budget and alert thresholds for this
                  organization.
                </p>
              </div>
              <button
                type="button"
                onClick={closeBudgetModal}
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
                  onClick={closeBudgetModal}
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
          {serviceData.length > 0 ? (
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
          ) : (
            <div className="flex h-[300px] items-center justify-center text-sm text-gray-500 dark:text-gray-400">
              {loading
                ? "Loading persisted service cost data..."
                : "No persisted cost records are available for this organization yet."}
            </div>
          )}
        </div>
        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Daily Cost Trend
          </h3>
          {dailyTrendData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={dailyTrendData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="cost" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-[300px] items-center justify-center text-sm text-gray-500 dark:text-gray-400">
              {loading
                ? "Loading persisted daily cost trend..."
                : "No daily cost trend is available until backend cost records are created."}
            </div>
          )}
        </div>
      </div>
      {/* Per-resource costs */}
      <div className="card" data-tour="cost-by-resource">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Cost by Resource
        </h3>
        {resourceCosts?.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm" data-testid="resource-cost-table">
              <thead>
                <tr className="text-left text-gray-500 dark:text-gray-400">
                  <th className="py-2 pr-4">Resource</th>
                  <th className="py-2 pr-4">Type</th>
                  <th className="py-2 pr-4 text-right">Compute</th>
                  <th className="py-2 pr-4 text-right">Storage</th>
                  <th className="py-2 pr-4 text-right">Network</th>
                  <th className="py-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody className="text-gray-900 dark:text-white">
                {resourceCosts.map((row) => (
                  <tr key={row.resource_id} className="border-t border-gray-200 dark:border-gray-700">
                    <td className="py-2 pr-4">{row.name}</td>
                    <td className="py-2 pr-4 uppercase">{row.resource_type}</td>
                    <td className="py-2 pr-4 text-right">${Number(row.compute_cost || 0).toFixed(4)}</td>
                    <td className="py-2 pr-4 text-right">${Number(row.storage_cost || 0).toFixed(4)}</td>
                    <td className="py-2 pr-4 text-right">${Number(row.network_cost || 0).toFixed(4)}</td>
                    <td className="py-2 text-right font-medium">${Number(row.total_cost || 0).toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {resourceCosts === null
              ? "Loading per-resource costs..."
              : "No resources with cost data yet."}
          </p>
        )}
      </div>
      {/* Budgets */}
      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Budgets
        </h3>
        {activeBudgets.length > 0 ? (
          <div className="space-y-3">
            {activeBudgets.map((budget) => (
              <div
                key={budget.id}
                className="flex flex-col gap-2 rounded-lg bg-gray-50 p-4 dark:bg-gray-700/50 sm:flex-row sm:items-center sm:justify-between"
              >
                <div>
                  <p className="font-medium text-gray-900 dark:text-white">
                    {budget.name} <span className="text-xs text-gray-500">({budget.period})</span>
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    ${Number(budget.current_spend).toFixed(2)} of ${Number(budget.amount).toFixed(2)} ({Number(budget.percentage_used).toFixed(1)}%), alert level: {budget.alert_level}
                  </p>
                </div>
                {canManageBudgets && (
                  <div className="flex gap-3 text-sm">
                    <button type="button" onClick={() => openEditBudget(budget)} className="text-primary-600 hover:underline">
                      Edit
                    </button>
                    <button type="button" onClick={() => deleteBudget(budget)} className="text-red-600 hover:underline">
                      Delete
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            No budgets yet.{canManageBudgets ? " Use Create Budget to add one." : ""}
          </p>
        )}
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
                    {item.recommendation}
                  </p>
                  {item.reason && (
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      Rule {item.rule}: {item.reason}
                    </p>
                  )}
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold text-success-600">
                    Save ${item.potential_monthly_savings?.toFixed(2) || "0.00"}
                    /mo
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">estimated</p>
                </div>
              </div>
            ))
          ) : (
            <div className="rounded-lg bg-gray-50 p-4 text-sm text-gray-600 dark:bg-gray-700/50 dark:text-gray-300">
              {loading
                ? "Loading backend optimization recommendations..."
                : hasCostData
                  ? "No backend optimization recommendations are active for the current persisted resource state."
                  : "Recommendations will appear here after backend cost records and active resources are available."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
export default CostManagement;
