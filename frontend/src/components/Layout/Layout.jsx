import React, { useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { useDispatch, useSelector } from "react-redux";
import { fetchProfile, logoutUser } from "../../store/slices/authSlice";
import { fetchOrganizations, switchOrganization } from "../../store/slices/organizationSlice";
import { clearSettings, fetchSettings } from "../../store/slices/settingsSlice";
import { fetchVMs } from "../../store/slices/resourceSlice";
import Sidebar from "./Sidebar";
import Header from "./Header";
import AIChatbox from "../Assistant/AIChatbox";
import { TourProvider } from "../../tour/TourProvider";

const Layout = () => {
  const dispatch = useDispatch();
  const location = useLocation();
  const navigate = useNavigate();
  const settings = useSelector((state) => state.settings.data);
  const lastActivity = useRef(Date.now());
  const { isAuthenticated } = useSelector((state) => state.auth);
  const { organizations, currentOrganization } = useSelector(
    (state) => state.organization,
  );

  const currentRole =
    currentOrganization?.role ||
    currentOrganization?.my_role ||
    organizations.find((o) => o.id === currentOrganization?.id)?.role ||
    null;

  const isViewer = currentRole === "viewer";
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Close the mobile menu on navigation; the guided tour can also open/close it.
  useEffect(() => setSidebarOpen(false), [location.pathname]);
  useEffect(() => {
    const onTour = (e) => setSidebarOpen(Boolean(e.detail?.open));
    window.addEventListener("fyp-tour-sidebar", onTour);
    return () => window.removeEventListener("fyp-tour-sidebar", onTour);
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    dispatch(fetchProfile());
    dispatch(fetchOrganizations());
    dispatch(fetchSettings()); // applies the saved theme as soon as it arrives
  }, [dispatch, isAuthenticated]);

  // Saved default organization: applied once at the start of each browser session.
  useEffect(() => {
    const defaultOrgId = settings?.dashboard?.default_organization_id;
    if (!defaultOrgId || organizations.length === 0) return;
    let applied = null;
    try { applied = sessionStorage.getItem("fyp:default-org-applied"); } catch (_e) { /* storage blocked */ }
    if (applied) return;
    const target = organizations.find((o) => o.id === defaultOrgId);
    if (target && target.id !== currentOrganization?.id) dispatch(switchOrganization(target));
    try { sessionStorage.setItem("fyp:default-org-applied", "1"); } catch (_e) { /* ignore */ }
  }, [settings?.dashboard?.default_organization_id, organizations, currentOrganization?.id, dispatch]);

  // Sign out after the saved period of inactivity (Settings → Security).
  useEffect(() => {
    const minutes = settings?.security?.session_timeout;
    if (!isAuthenticated || !minutes) return undefined;
    const touch = () => { lastActivity.current = Date.now(); };
    const events = ["mousedown", "keydown", "scroll", "touchstart"];
    events.forEach((e) => window.addEventListener(e, touch, { passive: true }));
    const timer = window.setInterval(async () => {
      if (Date.now() - lastActivity.current > minutes * 60 * 1000) {
        window.clearInterval(timer);
        await dispatch(logoutUser());
        dispatch(clearSettings());
        try { sessionStorage.removeItem("fyp:default-org-applied"); } catch (_e) { /* ignore */ }
        toast(`Signed out after ${minutes} minutes of inactivity.`);
        navigate("/login");
      }
    }, 30000);
    return () => {
      window.clearInterval(timer);
      events.forEach((e) => window.removeEventListener(e, touch));
    };
  }, [settings?.security?.session_timeout, isAuthenticated, dispatch, navigate]);

  useEffect(() => {
    if (currentOrganization?.id) {
      dispatch(fetchVMs(currentOrganization.id));
    }
  }, [dispatch, currentOrganization?.id]);

  useEffect(() => {
    const pathname = location.pathname || "/";
    const key =
      pathname === "/"
        ? "dashboard"
        : pathname.replace(/^\/+/, "").split("/")[0];
    if (key) {
      localStorage.setItem(`scenario:page_visited:${key}`, "true");
    }
  }, [location.pathname]);

  return (
    <TourProvider>
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[10002] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-700 focus:shadow-lg">
        Skip to main content
      </a>
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex-1 flex flex-col min-w-0 lg:ml-64">
        <Header onMenuClick={() => setSidebarOpen(true)} />
        {isViewer && (
          <div className="bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-200 dark:border-yellow-700 px-6 py-2 flex items-center gap-2">
            <span>👁</span>
            <p className="text-sm text-yellow-800 dark:text-yellow-200">
              You are viewing{" "}
              <strong>{currentOrganization?.name}</strong> as a Viewer. You
              cannot create or modify resources.
            </p>
          </div>
        )}
        <main id="main-content" tabIndex={-1} className="flex-1 p-4 sm:p-6 overflow-auto focus:outline-none">
          <Outlet />
        </main>
      </div>
      <AIChatbox />
    </div>
    </TourProvider>
  );
};
export default Layout;
