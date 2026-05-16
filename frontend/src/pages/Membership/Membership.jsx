import React, { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import axios from 'axios';
import { CheckIcon, SparklesIcon, BoltIcon, BuildingOfficeIcon } from '@heroicons/react/24/outline';

const API_URL = process.env.REACT_APP_API_URL || '/api';

const fallbackPlans = [
  {
    id: 'starter',
    name: 'Starter',
    price: 'For demo use',
    badge: 'Current simulator access',
    icon: SparklesIcon,
    features: [
      'Dashboard, resources, security, cost, governance, and settings',
      'Single organization workspace',
      'Basic simulated cloud actions',
      'Local AI assistant support',
    ],
    future: 'Good for individual students and basic project demos.',
  },
  {
    id: 'pro',
    name: 'Pro',
    price: 'Future upgrade',
    badge: 'Advanced tools',
    icon: BoltIcon,
    features: [
      'Higher resource limits',
      'Advanced security analytics',
      'Improved cost forecasting',
      'Policy automation templates',
    ],
    future: 'Could be used if the project later grows into a larger multi-user platform.',
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    price: 'Future upgrade',
    badge: 'Team / institution plan',
    icon: BuildingOfficeIcon,
    features: [
      'Multiple organizations and teams',
      'Custom governance rules',
      'Audit exports and reporting',
      'Dedicated support and deployment options',
    ],
    future: 'Fits a future campus, lab, or company-wide rollout.',
  },
];

const iconByPlanId = {
  starter: SparklesIcon,
  pro: BoltIcon,
  enterprise: BuildingOfficeIcon,
};

const normalizePlans = (plans) => {
  if (!Array.isArray(plans) || plans.length === 0) return fallbackPlans;

  return plans.map((plan) => ({
    ...plan,
    icon: iconByPlanId[plan.id] || SparklesIcon,
    features: Array.isArray(plan.features) ? plan.features : [],
    badge: plan.badge || 'Available',
    price: plan.price || 'Included',
    future: plan.future || plan.description || 'Available in this simulator tier.',
  }));
};

const Membership = () => {
  const { token } = useSelector((state) => state.auth);
  const { currentOrganization } = useSelector((state) => state.organization);
  const [plans, setPlans] = useState(fallbackPlans);
  const [currentPlan, setCurrentPlan] = useState('starter');
  const [apiWarning, setApiWarning] = useState('');

  useEffect(() => {
    const loadPlans = async () => {
      if (!token) {
        setPlans(fallbackPlans);
        setCurrentPlan('starter');
        setApiWarning('');
        return;
      }

      try {
        const response = await axios.get(
          `${API_URL}/membership/plans${currentOrganization?.id ? `?organization_id=${currentOrganization.id}` : ''}`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        const payload = response.data?.data || response.data || {};
        setPlans(normalizePlans(payload.plans));
        setCurrentPlan(payload.current_plan || 'starter');
        setApiWarning('');
      } catch {
        setPlans(fallbackPlans);
        setCurrentPlan('starter');
        setApiWarning('Unable to load membership API, showing fallback plans.');
      }
    };

    loadPlans();
  }, [token, currentOrganization]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Membership Plans</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          This tab is a future-facing addition that can be used to present tiers, resource limits, and premium tools.
        </p>
        <p className="text-sm text-primary-600 mt-2">
          Current plan: <span className="font-semibold">{currentPlan.toUpperCase()}</span>
        </p>
        {apiWarning ? (
          <p className="text-sm text-amber-600 dark:text-amber-400 mt-2">{apiWarning}</p>
        ) : null}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {plans.map((plan) => {
          const PlanIcon = plan.icon || iconByPlanId[plan.id] || SparklesIcon;

          return (
            <div key={plan.id || plan.name} className="card flex flex-col h-full">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="w-12 h-12 rounded-2xl bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 flex items-center justify-center mb-4">
                    <PlanIcon className="w-6 h-6" />
                  </div>
                  <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{plan.name}</h2>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{plan.price}</p>
                </div>
                <span className="px-3 py-1 rounded-full text-xs font-semibold bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300">
                  {plan.badge}
                </span>
              </div>

              <ul className="mt-6 space-y-3 flex-1">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex items-start gap-3 text-sm text-gray-700 dark:text-gray-300">
                    <CheckIcon className="w-5 h-5 text-success-500 mt-0.5 flex-shrink-0" />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>

              <div className="mt-6 pt-4 border-t border-gray-200 dark:border-gray-700">
                <p className="text-sm text-gray-600 dark:text-gray-400">{plan.future}</p>
              </div>
            </div>
          );
        })}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">How this can be used later</h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
          In a future version, membership can control quotas, advanced reports, premium AI assistant behavior,
          team collaboration, and deployment options while keeping the core simulator available to everyone.
        </p>
      </div>
    </div>
  );
};

export default Membership;
