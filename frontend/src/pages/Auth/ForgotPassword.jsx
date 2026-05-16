import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import toast from 'react-hot-toast';

const API_URL = process.env.REACT_APP_API_URL || '/api';

const ForgotPassword = () => {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [responseMessage, setResponseMessage] = useState('');
  const [deliveryConfigured, setDeliveryConfigured] = useState(true);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const response = await axios.post(`${API_URL}/auth/forgot-password`, { email });
      setResponseMessage(
        response?.data?.data?.message ||
          "If that email is registered and reset delivery is configured, you'll receive a link shortly."
      );
      setDeliveryConfigured(response?.data?.data?.delivery_configured !== false);
      setSent(true);
    } catch (err) {
      toast.error(err?.response?.data?.error?.message || 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primary-50 to-primary-100 dark:from-gray-900 dark:to-gray-800">
      <div className="max-w-md w-full mx-4">
        <div className="card space-y-6">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Forgot Password</h1>
            <p className="text-gray-500 dark:text-gray-400 mt-2">
              Enter your email to request a reset link. Delivery depends on whether password reset email is configured for this environment.
            </p>
          </div>

          {sent ? (
            <div
              className={`rounded-lg border p-4 text-sm ${
                deliveryConfigured
                  ? 'bg-green-50 text-green-800 border-green-200 dark:bg-green-900/20 dark:border-green-700 dark:text-green-300'
                  : 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-900/20 dark:border-amber-700 dark:text-amber-300'
              }`}
            >
              {responseMessage}
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Email Address
                </label>
                <input
                  type="email"
                  required
                  className="input-field"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full btn-primary py-3 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? 'Sending...' : 'Send Reset Link'}
              </button>
            </form>
          )}

          <p className="text-center text-sm text-gray-600 dark:text-gray-400">
            Remember your password?{' '}
            <Link to="/login" className="text-primary-600 hover:text-primary-500 font-medium">
              Back to Sign In
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
};

export default ForgotPassword;
