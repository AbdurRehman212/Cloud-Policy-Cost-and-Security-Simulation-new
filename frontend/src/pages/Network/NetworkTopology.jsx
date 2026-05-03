import React, { useCallback, useEffect, useState } from "react";
import { useSelector } from "react-redux";
import axios from "axios";
import toast from "react-hot-toast";
import {
  GlobeAltIcon,
  LockClosedIcon,
  ServerIcon,
  CircleStackIcon,
  ChevronDownIcon,
} from "@heroicons/react/24/outline";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:5000/api";

const STATUS_BADGE = {
  running: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  stopped: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400",
  pending: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
};

export default function NetworkTopology() {
  const { token } = useSelector((s) => s.auth);
  const { currentOrganization } = useSelector((s) => s.organization);
  const orgId = currentOrganization?.id;

  const [vpcs, setVpcs] = useState([]);
  const [topology, setTopology] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  const loadData = useCallback(async () => {
    if (!orgId) return;
    setLoading(true);
    try {
      const [vpcRes, topoRes] = await Promise.all([
        axios.get(`${API_URL}/resources/vpcs`, {
          headers,
          params: { organization_id: orgId },
        }),
        axios.get(`${API_URL}/resources/network/topology`, {
          headers,
          params: { organization_id: orgId },
        }),
      ]);
      setVpcs(vpcRes.data?.data || []);
      setTopology(topoRes.data?.data || null);
    } catch {
      toast.error("Failed to load network topology");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const defaultVpc = vpcs.find((v) => v.is_default) || vpcs[0] || null;
  const topoVpc = topology?.vpcs?.[0] || null;
  const subnets = topoVpc?.subnets || [];
  const publicSubnet = subnets.find((s) => s.subnet_type === "public");
  const privateSubnet = subnets.find((s) => s.subnet_type === "private");

  const totalVms = subnets.reduce((n, s) => n + (s.vms?.length || 0), 0);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary-600" />
      </div>
    );
  }

  return (
    <div className="flex gap-6">
      {/* Main content */}
      <div className="min-w-0 flex-1 space-y-6">
        {/* Page header */}
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Network Topology
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Your virtual private cloud architecture
          </p>
        </div>

        {/* VPC Info bar */}
        {defaultVpc ? (
          <div className="rounded-xl border border-gray-200 bg-white px-5 py-4 dark:border-gray-700 dark:bg-gray-800">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
              <span className="font-semibold text-gray-900 dark:text-white text-base">
                {defaultVpc.name}
              </span>
              <span className="text-gray-500 dark:text-gray-400">
                CIDR: <span className="font-mono text-gray-700 dark:text-gray-300">{defaultVpc.cidr_block}</span>
              </span>
              <span className="text-gray-500 dark:text-gray-400">
                Region: <span className="font-medium text-gray-700 dark:text-gray-300">{defaultVpc.region || "us-east-1"}</span>
              </span>
              <span className="text-gray-500 dark:text-gray-400">
                {(defaultVpc.subnets?.length || subnets.length)} Subnets
              </span>
              <span className="text-gray-500 dark:text-gray-400">
                {totalVms} VM{totalVms !== 1 ? "s" : ""}
              </span>
              <span className="rounded-full bg-primary-50 px-2.5 py-0.5 text-xs font-semibold text-primary-700 dark:bg-primary-900/20 dark:text-primary-300">
                Default VPC
              </span>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 px-5 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
            No VPC found. Create an organization to generate a default VPC.
          </div>
        )}

        {/* Subnet cards */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Public Subnet */}
          <SubnetCard
            subnet={publicSubnet}
            type="public"
            fallbackName="public-subnet-1"
            fallbackCidr="10.0.1.0/24"
            fallbackAz="us-east-1a"
          />
          {/* Private Subnet */}
          <SubnetCard
            subnet={privateSubnet}
            type="private"
            fallbackName="private-subnet-1"
            fallbackCidr="10.0.2.0/24"
            fallbackAz="us-east-1b"
          />
        </div>

        {/* Legend */}
        <div className="card p-5">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Connection Legend
          </h2>
          <div className="space-y-3 text-sm">
            <LegendRow
              color="text-green-600 dark:text-green-400"
              left="Public Subnet"
              arrow="→"
              middle="Internet Gateway"
              arrow2="→"
              right="Internet"
              leftBg="bg-green-50 dark:bg-green-900/20"
            />
            <LegendRow
              color="text-blue-600 dark:text-blue-400"
              left="Private Subnet"
              arrow="→"
              middle="NAT Gateway"
              arrow2="→"
              right="Internet (outbound only)"
              leftBg="bg-blue-50 dark:bg-blue-900/20"
            />
            <LegendRow
              color="text-purple-600 dark:text-purple-400"
              left="EC2 Instance"
              arrow="↔"
              middle="RDS / Database"
              arrow2=" "
              right="Private IP (no internet)"
              leftBg="bg-purple-50 dark:bg-purple-900/20"
            />
          </div>
        </div>
      </div>

      {/* Learning panel */}
      {sidebarOpen ? (
        <aside className="w-72 shrink-0">
          <div className="sticky top-6 rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
            <div className="flex items-start justify-between gap-3 mb-4">
              <h3 className="text-base font-bold text-gray-900 dark:text-white">
                What is a VPC?
              </h3>
              <button
                type="button"
                onClick={() => setSidebarOpen(false)}
                className="shrink-0 rounded p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              >
                <ChevronDownIcon className="h-4 w-4 rotate-90" />
              </button>
            </div>
            <div className="space-y-3 text-sm text-gray-600 dark:text-gray-300">
              <p>
                A <strong>Virtual Private Cloud</strong> is your isolated
                network in the cloud. AWS gives every account a default VPC
                with public and private subnets.
              </p>
              <p>
                <span className="font-semibold text-green-700 dark:text-green-400">
                  Public subnet:
                </span>{" "}
                resources here get a public IP and can receive internet traffic.
              </p>
              <p>
                <span className="font-semibold text-blue-700 dark:text-blue-400">
                  Private subnet:
                </span>{" "}
                resources here have no public IP. Used for databases — best
                practice.
              </p>
            </div>
            <div className="mt-4 space-y-2">
              <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-700/50">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                  AWS Equivalent
                </p>
                <p className="mt-0.5 text-sm font-medium text-gray-800 dark:text-gray-200">
                  Amazon VPC
                </p>
              </div>
              <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-700/50">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
                  Azure Equivalent
                </p>
                <p className="mt-0.5 text-sm font-medium text-gray-800 dark:text-gray-200">
                  Azure Virtual Network (VNet)
                </p>
              </div>
            </div>
          </div>
        </aside>
      ) : (
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          className="shrink-0 self-start rounded-xl border border-gray-200 bg-white px-3 py-4 text-xs font-semibold text-gray-500 shadow hover:border-primary-400 hover:text-primary-600 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-primary-500"
          style={{ writingMode: "vertical-rl" }}
        >
          Learn
        </button>
      )}
    </div>
  );
}

function SubnetCard({ subnet, type, fallbackName, fallbackCidr, fallbackAz }) {
  const isPublic = type === "public";
  const name = subnet?.name || fallbackName;
  const cidr = subnet?.cidr_block || fallbackCidr;
  const az = subnet?.availability_zone || fallbackAz;
  const vms = subnet?.vms || [];
  const dbs = subnet?.databases || [];

  const borderColor = isPublic
    ? "border-green-300 dark:border-green-700"
    : "border-blue-300 dark:border-blue-700";
  const badgeColor = isPublic
    ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
    : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
  const headerBg = isPublic
    ? "bg-green-50 dark:bg-green-900/10"
    : "bg-blue-50 dark:bg-blue-900/10";

  return (
    <div className={`rounded-xl border-2 ${borderColor} bg-white dark:bg-gray-800 overflow-hidden`}>
      <div className={`${headerBg} px-5 py-4`}>
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold text-gray-900 dark:text-white">{name}</h3>
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${badgeColor}`}>
            {isPublic ? "PUBLIC" : "PRIVATE"}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
          <span className="font-mono">{cidr}</span>
          <span>AZ: {az}</span>
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-xs font-medium">
          {isPublic ? (
            <>
              <GlobeAltIcon className="h-4 w-4 text-green-600 dark:text-green-400" />
              <span className="text-green-700 dark:text-green-400">Internet accessible</span>
            </>
          ) : (
            <>
              <LockClosedIcon className="h-4 w-4 text-blue-600 dark:text-blue-400" />
              <span className="text-blue-700 dark:text-blue-400">No direct internet access</span>
            </>
          )}
        </div>
      </div>

      <div className="divide-y divide-gray-100 dark:divide-gray-700 px-5 py-3">
        {vms.length === 0 && dbs.length === 0 ? (
          <p className="py-3 text-sm text-gray-400 dark:text-gray-500">
            No resources in this subnet
          </p>
        ) : (
          <>
            {vms.map((vm) => (
              <ResourceRow
                key={`vm-${vm.id}`}
                icon={<ServerIcon className="h-4 w-4 text-primary-500" />}
                name={vm.name}
                status={vm.status}
                detail={vm.instance_type}
                ip={vm.ip}
              />
            ))}
            {!isPublic &&
              dbs.map((db) => (
                <ResourceRow
                  key={`db-${db.id}`}
                  icon={<CircleStackIcon className="h-4 w-4 text-amber-500" />}
                  name={db.name}
                  status={db.status}
                  detail="database"
                  ip={null}
                />
              ))}
          </>
        )}
      </div>
    </div>
  );
}

function ResourceRow({ icon, name, status, detail, ip }) {
  return (
    <div className="flex items-center gap-3 py-2.5 text-sm">
      <span className="shrink-0">{icon}</span>
      <span className="min-w-0 flex-1 truncate font-medium text-gray-800 dark:text-gray-200">
        {name}
      </span>
      {status && (
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_BADGE[status] || STATUS_BADGE.pending}`}>
          {status}
        </span>
      )}
      {detail && (
        <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500">{detail}</span>
      )}
      {ip && (
        <span className="shrink-0 font-mono text-xs text-gray-400 dark:text-gray-500">{ip}</span>
      )}
    </div>
  );
}

function LegendRow({ color, left, arrow, middle, arrow2, right, leftBg }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className={`rounded px-2 py-0.5 text-xs font-semibold ${leftBg} ${color}`}>
        {left}
      </span>
      <span className="font-bold text-gray-400">{arrow}</span>
      <span className="text-gray-600 dark:text-gray-300">{middle}</span>
      {arrow2.trim() && <span className="font-bold text-gray-400">{arrow2}</span>}
      <span className="text-gray-500 dark:text-gray-400">{right}</span>
    </div>
  );
}
