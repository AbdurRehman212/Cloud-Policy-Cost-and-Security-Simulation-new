import React, { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useLocation } from "react-router-dom";
import { useSelector } from "react-redux";
import Sidebar from "./Sidebar";
import Header from "./Header";
import AIChatbox from "../Assistant/AIChatbox";

const Layout = () => {
  const location = useLocation();
  const { organizations, currentOrganization } = useSelector(
    (state) => state.organization,
  );

  const currentRole =
    currentOrganization?.role ||
    currentOrganization?.my_role ||
    organizations.find((o) => o.id === currentOrganization?.id)?.role ||
    null;

  const isViewer = currentRole === "viewer";

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
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex">
      <Sidebar />
      <div className="flex-1 flex flex-col ml-64">
        <Header />
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
        <main className="flex-1 p-6 overflow-auto">
          <Outlet />
        </main>
      </div>
      <AIChatbox />
    </div>
  );
};
export default Layout;
