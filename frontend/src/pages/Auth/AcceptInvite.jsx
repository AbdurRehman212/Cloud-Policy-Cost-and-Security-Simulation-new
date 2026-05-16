import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import axios from 'axios';
import toast from 'react-hot-toast';
import { fetchOrganizations, switchOrganization } from '../../store/slices/organizationSlice';

const API_URL = process.env.REACT_APP_API_URL || '/api';

const AcceptInvite = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const token = searchParams.get('token');
  const { isAuthenticated, token: authToken } = useSelector((state) => state.auth);

  const [status, setStatus] = useState('idle'); // 'idle' | 'accepting' | 'success' | 'error'
  const [message, setMessage] = useState('');

  const handleAccept = async () => {
    setStatus('accepting');
    try {
      const res = await axios.post(
        `${API_URL}/org/accept-invite`,
        { token },
        { headers: { Authorization: `Bearer ${authToken}` } }
      );
      setStatus('success');
      setMessage(res.data?.data?.message || 'You have joined the organization.');
      const result = await dispatch(fetchOrganizations());
      const orgs = result?.payload || [];
      const targetOrgId = res.data?.data?.organization_id;
      const targetOrg = orgs.find((org) => org.id === targetOrgId || org.organization_id === targetOrgId);
      if (targetOrg) {
        dispatch(switchOrganization(targetOrg));
      }
      setTimeout(() => navigate('/', { replace: true }), 2000);
    } catch (err) {
      setStatus('error');
      setMessage(err?.response?.data?.error?.message || 'Failed to accept invitation.');
      toast.error(err?.response?.data?.error?.message || 'Failed to accept invitation.');
    }
  };

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primary-50 to-primary-100 dark:from-gray-900 dark:to-gray-800">
        <div className="max-w-md w-full mx-4">
          <div className="card space-y-4 text-center">
            <p className="text-red-600 dark:text-red-400 font-medium">Invalid invitation link — no token found.</p>
            <Link to="/" className="btn-primary inline-block">Go to Dashboard</Link>
          </div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primary-50 to-primary-100 dark:from-gray-900 dark:to-gray-800">
        <div className="max-w-md w-full mx-4">
          <div className="card space-y-4 text-center">
            <div className="text-4xl">📩</div>
            <h1 className="text-xl font-bold text-gray-900 dark:text-white">Organization Invitation</h1>
            <p className="text-gray-600 dark:text-gray-400">
              You need to be signed in to accept this invitation.
            </p>
            <Link
              to={`/login?redirect=/accept-invite%3Ftoken%3D${token}`}
              className="btn-primary inline-block px-6 py-2"
            >
              Sign In to Continue
            </Link>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Don't have an account?{' '}
              <Link
                to={`/register?redirect=/accept-invite%3Ftoken%3D${token}`}
                className="text-primary-600 hover:text-primary-500"
              >
                Register
              </Link>
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primary-50 to-primary-100 dark:from-gray-900 dark:to-gray-800">
      <div className="max-w-md w-full mx-4">
        <div className="card space-y-6 text-center">
          {status === 'idle' && (
            <>
              <div className="text-4xl">📩</div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-white">Organization Invitation</h1>
              <p className="text-gray-600 dark:text-gray-400">
                You've been invited to join an organization on the Cloud Policy, Cost &amp; Security Simulator.
              </p>
              <div className="flex flex-col gap-3">
                <button
                  onClick={handleAccept}
                  className="btn-primary py-2"
                >
                  Accept Invitation
                </button>
                <Link to="/" className="btn-secondary py-2 text-center">
                  Decline
                </Link>
              </div>
            </>
          )}

          {status === 'accepting' && (
            <>
              <div className="flex justify-center">
                <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary-600 border-t-transparent" />
              </div>
              <p className="text-gray-600 dark:text-gray-400">Accepting invitation…</p>
            </>
          )}

          {status === 'success' && (
            <>
              <div className="text-5xl">✅</div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-white">Invitation Accepted</h1>
              <p className="text-gray-600 dark:text-gray-400">{message}</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">Redirecting to dashboard…</p>
            </>
          )}

          {status === 'error' && (
            <>
              <div className="text-5xl">❌</div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-white">Invitation Failed</h1>
              <p className="text-red-600 dark:text-red-400">{message}</p>
              <Link to="/" className="btn-primary inline-block">Go to Dashboard</Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default AcceptInvite;
