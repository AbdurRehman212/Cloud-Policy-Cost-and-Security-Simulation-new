import React, { useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import axios from 'axios';
import { logout } from '../../store/slices/authSlice';
import {
  fetchOrganizations,
  switchOrganization,
} from '../../store/slices/organizationSlice';
import {
  ArrowRightOnRectangleIcon,
  BellIcon,
  BuildingOfficeIcon,
  CheckIcon,
  ChevronDownIcon,
  PlusIcon,
  UserCircleIcon,
} from '@heroicons/react/24/outline';
import UserProgressBar from './UserProgressBar';

const ROLE_COLORS = {
  owner: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
  admin: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  member: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  viewer: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300',
};

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000/api';

const Header = () => {
  const dispatch = useDispatch();
  const { user, token } = useSelector((state) => state.auth);
  const { organizations, currentOrganization } = useSelector((state) => state.organization);

  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newOrgName, setNewOrgName] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const dropdownRef = useRef(null);

  const currentRole = currentOrganization?.role || currentOrganization?.my_role || 'member';

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleCreateOrg = async (e) => {
    e.preventDefault();
    if (!newOrgName.trim()) return;
    setCreating(true);
    setCreateError('');
    try {
      await axios.post(
        `${API_URL}/org/`,
        { name: newOrgName.trim() },
        { headers: { Authorization: `Bearer ${token}` } },
      );
      const result = await dispatch(fetchOrganizations());
      const orgs = result?.payload || [];
      const created = orgs.find((o) => o.name === newOrgName.trim());
      if (created) dispatch(switchOrganization(created));
      setNewOrgName('');
      setCreateModalOpen(false);
      setDropdownOpen(false);
    } catch (err) {
      setCreateError(err?.response?.data?.error?.message || 'Failed to create organization');
    } finally {
      setCreating(false);
    }
  };

  return (
    <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4">
      <div className="flex items-center justify-between">
        {/* Org Switcher */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen((o) => !o)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          >
            <BuildingOfficeIcon className="w-5 h-5 text-gray-500 dark:text-gray-400 shrink-0" />
            <span className="font-semibold text-gray-900 dark:text-white text-sm">
              {currentOrganization?.name || 'Select Organization'}
            </span>
            {currentRole && (
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ROLE_COLORS[currentRole] || ROLE_COLORS.member}`}>
                {currentRole}
              </span>
            )}
            <ChevronDownIcon className="w-4 h-4 text-gray-400" />
          </button>

          {dropdownOpen && (
            <div className="absolute left-0 top-full mt-1 w-72 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg z-50">
              <div className="py-1 max-h-60 overflow-y-auto">
                {organizations.map((org) => {
                  const isActive = org.id === currentOrganization?.id;
                  const role = org.role || org.my_role || 'member';
                  return (
                    <button
                      key={org.id}
                      onClick={() => {
                        dispatch(switchOrganization(org));
                        setDropdownOpen(false);
                      }}
                      className={`w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors ${isActive ? 'bg-primary-50 dark:bg-primary-900/20' : ''}`}
                    >
                      <BuildingOfficeIcon className="w-4 h-4 text-gray-400 shrink-0" />
                      <span className="flex-1 text-sm font-medium text-gray-900 dark:text-white truncate">
                        {org.name}
                      </span>
                      <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${ROLE_COLORS[role] || ROLE_COLORS.member}`}>
                        {role}
                      </span>
                      {isActive && <CheckIcon className="w-4 h-4 text-primary-600 dark:text-primary-400 shrink-0" />}
                    </button>
                  );
                })}
              </div>
              <div className="border-t border-gray-200 dark:border-gray-700 p-2">
                {!createModalOpen ? (
                  <button
                    onClick={() => setCreateModalOpen(true)}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-primary-600 dark:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-900/20 rounded-lg transition-colors"
                  >
                    <PlusIcon className="w-4 h-4" />
                    Create Organization
                  </button>
                ) : (
                  <form onSubmit={handleCreateOrg} className="space-y-2 p-1">
                    <input
                      autoFocus
                      type="text"
                      value={newOrgName}
                      onChange={(e) => setNewOrgName(e.target.value)}
                      placeholder="Organization name"
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-1 focus:ring-primary-500 outline-none"
                    />
                    {createError && <p className="text-xs text-red-500">{createError}</p>}
                    <div className="flex gap-2">
                      <button
                        type="submit"
                        disabled={creating || !newOrgName.trim()}
                        className="flex-1 py-1.5 text-xs bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                      >
                        {creating ? 'Creating…' : 'Create'}
                      </button>
                      <button
                        type="button"
                        onClick={() => { setCreateModalOpen(false); setCreateError(''); setNewOrgName(''); }}
                        className="flex-1 py-1.5 text-xs bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600"
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right section */}
        <div className="flex items-center space-x-4">
          <UserProgressBar />
          <button className="relative p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
            <BellIcon className="w-6 h-6" />
            <span className="absolute top-1 right-1 w-2 h-2 bg-danger-500 rounded-full"></span>
          </button>
          <div className="flex items-center space-x-3 pl-4 border-l border-gray-200 dark:border-gray-700">
            <UserCircleIcon className="w-8 h-8 text-gray-400" />
            <div className="hidden md:block">
              <p className="text-sm font-medium text-gray-900 dark:text-white">
                {user?.first_name} {user?.last_name}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">{user?.email}</p>
            </div>
            <button
              onClick={() => dispatch(logout())}
              className="p-2 text-gray-500 hover:text-danger-600 dark:text-gray-400 dark:hover:text-danger-400"
              title="Logout"
            >
              <ArrowRightOnRectangleIcon className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
export default Header;
