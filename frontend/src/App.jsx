import React, { useEffect } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import { fetchProfile } from "./store/slices/authSlice";
import { fetchOrganizations } from "./store/slices/organizationSlice";
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
const PrivateRoute = ({ children }) => {
  const { isAuthenticated } = useSelector((state) => state.auth);
  return isAuthenticated ? children : <Navigate to="/login" />;
};
function App() {
  const dispatch = useDispatch();
  const { isAuthenticated } = useSelector((state) => state.auth);
  useEffect(() => {
    if (isAuthenticated) {
      dispatch(fetchProfile());
      dispatch(fetchOrganizations());
    }
  }, [dispatch, isAuthenticated]);
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route
        path="/"
        element={
          <PrivateRoute>
            <Layout />
          </PrivateRoute>
        }
      >
        <Route index element={<Dashboard />} />
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
      </Route>
    </Routes>
  );
}
export default App;
