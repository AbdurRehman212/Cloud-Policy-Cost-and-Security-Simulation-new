import React from "react";
import { NavLink } from "react-router-dom";
import { useSelector } from "react-redux";
import {
  AcademicCapIcon,
  HomeIcon,
  ServerIcon,
  ShieldCheckIcon,
  CurrencyDollarIcon,
  ClipboardDocumentCheckIcon,
  CreditCardIcon,
  Cog6ToothIcon,
  PencilSquareIcon,
  UserCircleIcon,
  BuildingOfficeIcon,
  GlobeAltIcon,
} from "@heroicons/react/24/outline";
const Sidebar = () => {
  const { currentOrganization } = useSelector((state) => state.organization);
  const navigation = [
    { name: "Dashboard", href: "/", icon: HomeIcon },
    { name: "🧪 Labs", href: "/scenarios", icon: AcademicCapIcon },
    { name: "Architecture", href: "/canvas", icon: PencilSquareIcon },
    { name: "Resources", href: "/resources", icon: ServerIcon },
    { name: "Security", href: "/security", icon: ShieldCheckIcon },
    { name: "Cost Management", href: "/cost", icon: CurrencyDollarIcon },
    {
      name: "Governance",
      href: "/governance",
      icon: ClipboardDocumentCheckIcon,
    },
    { name: "Membership", href: "/membership", icon: CreditCardIcon },
    { name: "Settings", href: "/settings", icon: Cog6ToothIcon },
    { name: "Network", href: "/network", icon: GlobeAltIcon },
    { name: "Organization", href: "/organization", icon: BuildingOfficeIcon },
    { name: "Profile", href: "/profile", icon: UserCircleIcon },
  ];
  return (
    <div className="fixed inset-y-0 left-0 w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col">
      <div className="flex items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 bg-primary-600 rounded-lg flex items-center justify-center">
            <CloudIcon className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-gray-900 dark:text-white">
              Cloud Policy, Cost & Security Simulator
            </h1>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Digital Twin | FYP 2026
            </p>
          </div>
        </div>
      </div>
      {currentOrganization && (
        <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">
          <p className="text-xs text-gray-500 dark:text-gray-400 uppercase font-semibold">
            Organization
          </p>
          <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
            {currentOrganization.name}
          </p>
        </div>
      )}
      <nav className="flex-1 px-4 py-4 space-y-1">
        {navigation.map((item) => (
          <NavLink
            key={item.name}
            to={item.href}
            className={({ isActive }) =>
              `sidebar-link ${isActive ? "active" : ""}`
            }
          >
            <item.icon className="w-5 h-5 mr-3" />
            {item.name}
          </NavLink>
        ))}
      </nav>
      <div className="p-4 border-t border-gray-200 dark:border-gray-700">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded-full bg-primary-100 dark:bg-primary-900 flex items-center justify-center">
            <span className="text-sm font-medium text-primary-600 dark:text-primary-400">
              AI
            </span>
          </div>
          <div className="flex-1">
            <p className="text-sm font-medium text-gray-900 dark:text-white">
              AI Assistant
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Ready to help
            </p>
          </div>
          <div className="w-2 h-2 bg-success-500 rounded-full animate-pulse"></div>
        </div>
      </div>
    </div>
  );
};
const CloudIcon = ({ className }) => (
  <svg
    className={className}
    fill="none"
    viewBox="0 0 24 24"
    stroke="currentColor"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
      d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z"
    />
  </svg>
);
export default Sidebar;
