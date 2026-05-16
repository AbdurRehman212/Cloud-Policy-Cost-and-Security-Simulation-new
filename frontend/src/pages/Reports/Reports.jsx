import React, { useState } from 'react';
import { useSelector } from 'react-redux';
import axios from 'axios';
import toast from 'react-hot-toast';
import {
  DocumentArrowDownIcon,
  TableCellsIcon,
  DocumentChartBarIcon,
} from '@heroicons/react/24/outline';

const API_URL = process.env.REACT_APP_API_URL || '/api';

const REPORT_TYPES = [
  {
    key: 'summary',
    label: 'Summary Report',
    description: 'Organization overview: resource count, active threats, month-to-date spend.',
    icon: DocumentChartBarIcon,
    endpoint: 'summary.pdf',
  },
  {
    key: 'cost',
    label: 'Cost Report',
    description: 'Persisted cost records with spend totals and 7-day historical comparison.',
    icon: DocumentChartBarIcon,
    endpoint: 'cost.pdf',
  },
  {
    key: 'security',
    label: 'Security Summary Report',
    description: 'Persisted threats and security logs with 7-day detection comparison.',
    icon: DocumentChartBarIcon,
    endpoint: 'security.pdf',
  },
];

const Spinner = () => (
  <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent inline-block mr-2" />
);

const Reports = () => {
  const { token } = useSelector((state) => state.auth);
  const { currentOrganization } = useSelector((state) => state.organization);
  const orgId = currentOrganization?.id;

  const [pdfLoading, setPdfLoading] = useState(null);
  const [csvLoading, setCsvLoading] = useState(null);

  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  const downloadBlob = (data, filename, mime) => {
    const url = window.URL.createObjectURL(new Blob([data], { type: mime }));
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const handleGeneratePdf = async (reportType, endpoint) => {
    if (!orgId) { toast.error('No organization selected'); return; }
    setPdfLoading(reportType);
    try {
      const res = await axios.get(
        `${API_URL}/reports/${endpoint}`,
        {
          params: { organization_id: orgId },
          headers,
          responseType: 'blob',
        }
      );
      downloadBlob(res.data, `${reportType}_report_${new Date().toISOString().slice(0,10)}.pdf`, 'application/pdf');
      toast.success(`${reportType} report downloaded`);
    } catch (err) {
      toast.error(err?.response?.data?.error?.message || 'Failed to generate PDF');
    } finally {
      setPdfLoading(null);
    }
  };

  const handleExportCsv = async (dataType) => {
    if (!orgId) { toast.error('No organization selected'); return; }
    setCsvLoading(dataType);
    try {
      const res = await axios.get(`${API_URL}/reports/export/csv`, {
        params: { organization_id: orgId, type: dataType },
        headers,
        responseType: 'blob',
      });
      downloadBlob(res.data, `${dataType}_export_${new Date().toISOString().slice(0,10)}.csv`, 'text/csv');
      toast.success(`${dataType} CSV downloaded`);
    } catch (err) {
      toast.error(err?.response?.data?.error?.message || 'Failed to export CSV');
    } finally {
      setCsvLoading(null);
    }
  };

  if (!orgId) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-500 dark:text-gray-400">No organization selected. Please select one from the sidebar.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Reports</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Generate PDF reports or export raw data as CSV for <strong>{currentOrganization?.name}</strong>.
        </p>
      </div>

      {/* PDF Reports */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center gap-2">
          <DocumentArrowDownIcon className="h-5 w-5 text-primary-600 dark:text-primary-400" />
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">PDF Reports</h2>
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Formatted PDF reports suitable for academic submission or stakeholder review.
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {REPORT_TYPES.map(({ key, label, description, icon: Icon, endpoint }) => (
            <div
              key={key}
              className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 p-4 flex flex-col gap-3"
            >
              <div className="flex items-start gap-3">
                <Icon className="h-5 w-5 mt-0.5 text-gray-500 dark:text-gray-400 shrink-0" />
                <div>
                  <p className="font-semibold text-sm text-gray-900 dark:text-white">{label}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
                </div>
              </div>
              <button
                onClick={() => handleGeneratePdf(key, endpoint)}
                disabled={pdfLoading === key}
                className="btn-primary text-sm py-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {pdfLoading === key ? <><Spinner />Generating…</> : 'Download PDF'}
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* CSV Exports */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center gap-2">
          <TableCellsIcon className="h-5 w-5 text-primary-600 dark:text-primary-400" />
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">CSV Data Exports</h2>
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Raw data exports for offline analysis or dataset verification.
        </p>
        <div className="flex flex-wrap gap-3">
          {[
            { key: 'costs', label: 'Cost Records (CSV)' },
            { key: 'security', label: 'Security Events (CSV)' },
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => handleExportCsv(key)}
              disabled={csvLoading === key}
              className="btn-secondary text-sm py-2 px-4 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {csvLoading === key ? <><Spinner />Exporting…</> : label}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600 dark:border-gray-700 dark:bg-gray-800/60 dark:text-gray-300">
        <p className="font-semibold text-gray-900 dark:text-white">Planned Delivery</p>
        <p className="mt-1">
          Scheduled report delivery is not configured in this environment. Reports are available for manual download only.
        </p>
      </div>

      {/* Info panel */}
      <div className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 p-4 text-sm text-blue-800 dark:text-blue-300">
        <strong>Note:</strong> Reports reflect live data from the simulation. Run a scenario and allow the DES engine to populate cost and threat records before generating reports for the best results.
      </div>
    </div>
  );
};

export default Reports;
