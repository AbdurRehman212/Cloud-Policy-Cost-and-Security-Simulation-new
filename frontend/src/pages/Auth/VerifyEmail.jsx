import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || '/api';

const VerifyEmail = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');

  const [status, setStatus] = useState('verifying'); // 'verifying' | 'success' | 'error'
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('No verification token found in the link.');
      return;
    }
    axios
      .get(`${API_URL}/auth/verify-email`, { params: { token } })
      .then((res) => {
        setStatus('success');
        setMessage(res.data?.data?.message || 'Email verified successfully.');
      })
      .catch((err) => {
        setStatus('error');
        setMessage(err?.response?.data?.error?.message || 'Verification failed.');
      });
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primary-50 to-primary-100 dark:from-gray-900 dark:to-gray-800">
      <div className="max-w-md w-full mx-4">
        <div className="card space-y-6 text-center">
          {status === 'verifying' && (
            <>
              <div className="flex justify-center">
                <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary-600 border-t-transparent" />
              </div>
              <p className="text-gray-600 dark:text-gray-400">Verifying your email…</p>
            </>
          )}

          {status === 'success' && (
            <>
              <div className="text-5xl">✅</div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Email Verified</h1>
              <p className="text-gray-600 dark:text-gray-400">{message}</p>
              <Link to="/login" className="btn-primary inline-block px-6 py-2">
                Sign In
              </Link>
            </>
          )}

          {status === 'error' && (
            <>
              <div className="text-5xl">❌</div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Verification Failed</h1>
              <p className="text-red-600 dark:text-red-400">{message}</p>
              <div className="flex flex-col gap-2">
                <Link to="/login" className="btn-primary inline-block px-6 py-2">
                  Back to Sign In
                </Link>
              </div>
            </>
          )}

          <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Final Year Project 2026 | SZABIST University
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default VerifyEmail;
