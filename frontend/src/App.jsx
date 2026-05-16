import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useSelector } from "react-redux";
import { Toaster } from "react-hot-toast";
import Layout from "./components/Layout/Layout";
import Login from "./pages/Auth/Login";
import Register from "./pages/Auth/Register";
import Dashboard from "./pages/Dashboard/Dashboard";
import Resources from "./pages/Resources/Resources";
import Scenarios from "./pages/Scenarios/Scenarios";
import ScenarioDetail from "./pages/Scenarios/ScenarioDetail";
import Security from "./pages/Security/Security";
import CostManagement from "./pages/Cost/CostManagement";
import Governance from "./pages/Governance/Governance";
import Membership from "./pages/Membership/Membership";
import Settings from "./pages/Settings/Settings";
import ArchitectureCanvas from "./pages/Canvas/ArchitectureCanvas";
import Profile from "./pages/Profile/Profile";
import Organization from "./pages/Organization/Organization";
import NetworkTopology from "./pages/Network/NetworkTopology";
import ForgotPassword from "./pages/Auth/ForgotPassword";
import ResetPassword from "./pages/Auth/ResetPassword";
import VerifyEmail from "./pages/Auth/VerifyEmail";
import AcceptInvite from "./pages/Auth/AcceptInvite";
import Reports from "./pages/Reports/Reports";

// Error boundary for dashboard resilience
class DashboardErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("[DashboardErrorBoundary]", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center p-6">
          <div className="max-w-md text-center">
            <div className="text-6xl mb-4">⚠️</div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
              Dashboard Temporarily Unavailable
            </h1>
            <p className="text-gray-600 dark:text-gray-400 mb-4">
              The dashboard encountered an error. Please refresh or try again.
            </p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
            >
              Refresh Page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const PrivateRoute = ({ children }) => {
  const { isAuthenticated } = useSelector((state) => state.auth);
  return isAuthenticated ? children : <Navigate to="/login" />;
};
function App() {
  return (
    <>
      <Toaster position="top-right" />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/accept-invite" element={<AcceptInvite />} />
        <Route
          path="/"
          element={
            <PrivateRoute>
              <Layout />
            </PrivateRoute>
          }
        >
          <Route
            index
            element={
              <DashboardErrorBoundary>
                <Dashboard />
              </DashboardErrorBoundary>
            }
          />
          <Route path="scenarios" element={<Scenarios />} />
          <Route path="scenarios/:id" element={<ScenarioDetail />} />
          <Route path="canvas" element={<ArchitectureCanvas />} />
          <Route path="resources" element={<Resources />} />
          <Route path="security" element={<Security />} />
          <Route path="cost" element={<CostManagement />} />
          <Route path="governance" element={<Governance />} />
          <Route path="membership" element={<Membership />} />
          <Route path="settings" element={<Settings />} />
          <Route path="profile" element={<Profile />} />
          <Route path="organization" element={<Organization />} />
          <Route path="network" element={<NetworkTopology />} />
          <Route path="reports" element={<Reports />} />
        </Route>
      </Routes>
    </>
  );
}
export default App;
