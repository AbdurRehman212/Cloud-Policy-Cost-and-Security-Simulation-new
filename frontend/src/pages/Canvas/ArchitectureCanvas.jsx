import React, { useState, useRef } from "react";
import {
  ServerIcon,
  CircleStackIcon,
  CloudIcon,
  ShieldCheckIcon,
  GlobeAltIcon,
  ScaleIcon,
  TrashIcon,
  PlusIcon,
  PlayIcon,
  DocumentArrowDownIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import axios from "axios";

const PALETTE_ITEMS = [
  {
    id: "ec2",
    name: "EC2 Instance",
    type: "vm",
    icon: ServerIcon,
    awsEquivalent: "Amazon EC2",
    cost: "$0.0116/hr (t2.micro)",
    realUse: "Web servers, API backends, batch processing",
  },
  {
    id: "rds",
    name: "RDS Database",
    type: "database",
    icon: CircleStackIcon,
    awsEquivalent: "Amazon RDS",
    cost: "$0.017/hr (db.t2.micro)",
    realUse: "Relational databases, SQL workloads",
  },
  {
    id: "s3",
    name: "S3 Bucket",
    type: "storage",
    icon: CloudIcon,
    awsEquivalent: "Amazon S3",
    cost: "$0.023/GB/month",
    realUse: "Object storage, static hosting, backups",
  },
  {
    id: "sg",
    name: "Security Group",
    type: "security",
    icon: ShieldCheckIcon,
    awsEquivalent: "AWS Security Group",
    cost: "Free",
    realUse: "Virtual firewall, inbound/outbound rules",
  },
  {
    id: "igw",
    name: "Internet Gateway",
    type: "gateway",
    icon: GlobeAltIcon,
    awsEquivalent: "AWS Internet Gateway",
    cost: "Free + data transfer",
    realUse: "Public internet access for VPC",
  },
  {
    id: "lb",
    name: "Load Balancer",
    type: "loadbalancer",
    icon: ScaleIcon,
    awsEquivalent: "AWS Elastic Load Balancer",
    cost: "$0.0225/hr + LCU",
    realUse: "Distribute traffic, high availability",
  },
];

const TEMPLATES = {
  "basic-web-app": {
    name: "Basic Web App",
    description: "This is a typical 3-tier web architecture",
    items: [
      { id: "igw-1", type: "gateway", x: 400, y: 50, name: "Internet Gateway" },
      {
        id: "lb-1",
        type: "loadbalancer",
        x: 400,
        y: 220,
        name: "Load Balancer",
      },
      { id: "ec2-1", type: "vm", x: 200, y: 390, name: "web-server-01" },
      { id: "ec2-2", type: "vm", x: 600, y: 390, name: "web-server-02" },
      { id: "rds-1", type: "database", x: 400, y: 560, name: "Primary DB" },
      { id: "sg-1", type: "security", x: 50, y: 390, name: "Web SG" },
    ],
    connections: [
      { from: "igw-1", to: "lb-1", label: "Public Access" },
      { from: "lb-1", to: "ec2-1", label: "Behind LB" },
      { from: "lb-1", to: "ec2-2", label: "Behind LB" },
      { from: "ec2-1", to: "rds-1", label: "DB Connection" },
      { from: "ec2-2", to: "rds-1", label: "DB Connection" },
      { from: "ec2-1", to: "sg-1", label: "Protected by" },
      { from: "ec2-2", to: "sg-1", label: "Protected by" },
    ],
  },
  "high-availability": {
    name: "High Availability Setup",
    description: "This prevents single point of failure",
    items: [
      {
        id: "lb-1",
        type: "loadbalancer",
        x: 400,
        y: 50,
        name: "Load Balancer",
      },
      { id: "ec2-1", type: "vm", x: 220, y: 220, name: "web-server-az1" },
      { id: "ec2-2", type: "vm", x: 580, y: 220, name: "web-server-az2" },
      { id: "rds-1", type: "database", x: 280, y: 390, name: "Primary DB" },
      { id: "rds-2", type: "database", x: 520, y: 390, name: "Read Replica" },
      { id: "sg-1", type: "security", x: 100, y: 220, name: "Web SG" },
    ],
    connections: [
      { from: "lb-1", to: "ec2-1", label: "AZ1 Traffic" },
      { from: "lb-1", to: "ec2-2", label: "AZ2 Traffic" },
      { from: "ec2-1", to: "rds-1", label: "DB Connection" },
      { from: "ec2-2", to: "rds-1", label: "DB Connection" },
      { from: "rds-1", to: "rds-2", label: "Replication" },
      { from: "ec2-1", to: "sg-1", label: "Protected by" },
      { from: "ec2-2", to: "sg-1", label: "Protected by" },
    ],
  },
  "static-website": {
    name: "Static Website",
    description: "Serverless static hosting — zero EC2 cost",
    items: [
      { id: "s3-1", type: "storage", x: 250, y: 200, name: "S3 Bucket" },
      {
        id: "cf-1",
        type: "loadbalancer",
        x: 550,
        y: 200,
        name: "CDN",
      },
    ],
    connections: [{ from: "cf-1", to: "s3-1", label: "Origin" }],
  },
};

const CONNECTION_LABELS = {
  "vm-database": "DB Connection",
  "vm-security": "Protected by",
  "vm-storage": "Attached",
  "vm-loadbalancer": "Behind LB",
  "gateway-loadbalancer": "Public Access",
  "database-database": "Replication",
  "loadbalancer-storage": "Origin",
};

const ArchitectureCanvas = () => {
  const [canvasItems, setCanvasItems] = useState([]);
  const [connections, setConnections] = useState([]);
  const [selectedItem, setSelectedItem] = useState(null);
  const [connectionMode, setConnectionMode] = useState(null);
  const [learningPanelOpen, setLearningPanelOpen] = useState(true);
  const [learningContent, setLearningContent] = useState(null);
  const [provisioningStatus, setProvisioningStatus] = useState({});
  const [draggedItem, setDraggedItem] = useState(null);
  const [zoom, setZoom] = useState(100);
  const [itemInfoPopup, setItemInfoPopup] = useState(null);
  const canvasRef = useRef(null);

  const MIN_ZOOM = 50;
  const MAX_ZOOM = 200;
  const ZOOM_STEP = 25;

  const handleZoomIn = () => {
    setZoom((prev) => Math.min(prev + ZOOM_STEP, MAX_ZOOM));
  };

  const handleZoomOut = () => {
    setZoom((prev) => Math.max(prev - ZOOM_STEP, MIN_ZOOM));
  };

  const handleWheel = (e) => {
    e.preventDefault();
    if (e.deltaY < 0) {
      handleZoomIn();
    } else {
      handleZoomOut();
    }
  };

  const getItemIcon = (type) => {
    const item = PALETTE_ITEMS.find((p) => p.type === type);
    return item ? item.icon : ServerIcon;
  };

  const handleDragStart = (e, item) => {
    setDraggedItem(item);
    e.dataTransfer.effectAllowed = "copy";
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  };

  const handleDrop = (e) => {
    e.preventDefault();
    if (!draggedItem || !canvasRef.current) return;

    const rect = canvasRef.current.getBoundingClientRect();
    const rawX = e.clientX - rect.left - 60;
    const rawY = e.clientY - rect.top - 40;

    // Snap to 50px grid
    const snappedX = Math.round(rawX / 50) * 50;
    const snappedY = Math.round(rawY / 50) * 50;

    const newItem = {
      id: `${draggedItem.type}-${Date.now()}`,
      type: draggedItem.type,
      x: snappedX,
      y: snappedY,
      name: draggedItem.name,
      status: "not-provisioned",
    };

    setCanvasItems([...canvasItems, newItem]);
    setLearningContent({
      type: "item-added",
      ...draggedItem,
    });
    setDraggedItem(null);
  };

  const handleItemClick = (item) => {
    if (connectionMode) {
      if (connectionMode.from !== item.id) {
        const fromType = canvasItems.find(
          (i) => i.id === connectionMode.from,
        )?.type;
        const toType = item.type;
        const connectionKey = `${fromType}-${toType}`;
        const reverseKey = `${toType}-${fromType}`;
        const label =
          CONNECTION_LABELS[connectionKey] ||
          CONNECTION_LABELS[reverseKey] ||
          "Connected";

        setConnections([
          ...connections,
          { from: connectionMode.from, to: item.id, label },
        ]);
        setLearningContent({
          type: "connection-added",
          from: canvasItems.find((i) => i.id === connectionMode.from),
          to: item,
          label,
        });
      }
      setConnectionMode(null);
    } else {
      setSelectedItem(item.id === selectedItem ? null : item.id);
      // Show info popup with item details
      const paletteItem = PALETTE_ITEMS.find((p) => p.type === item.type);
      if (paletteItem) {
        setItemInfoPopup({
          item,
          paletteItem,
          x: item.x + 140,
          y: item.y,
        });
      }
    }
  };

  const startConnection = (itemId) => {
    setConnectionMode({ from: itemId });
  };

  const deleteItem = (itemId) => {
    setCanvasItems(canvasItems.filter((i) => i.id !== itemId));
    setConnections(
      connections.filter((c) => c.from !== itemId && c.to !== itemId),
    );
    if (selectedItem === itemId) setSelectedItem(null);
  };

  const loadTemplate = (templateKey) => {
    const template = TEMPLATES[templateKey];
    if (template) {
      setCanvasItems(template.items);
      setConnections(template.connections);
      setLearningContent({
        type: "template-loaded",
        name: template.name,
        description: template.description,
      });
    }
  };

  const clearCanvas = () => {
    setCanvasItems([]);
    setConnections([]);
    setSelectedItem(null);
    setConnectionMode(null);
    setProvisioningStatus({});
  };

  const saveCanvas = () => {
    const canvasData = { items: canvasItems, connections };
    localStorage.setItem("architecture-canvas", JSON.stringify(canvasData));
    alert("Architecture saved to localStorage!");
  };

  const loadSavedCanvas = () => {
    const saved = localStorage.getItem("architecture-canvas");
    if (saved) {
      const canvasData = JSON.parse(saved);
      setCanvasItems(canvasData.items || []);
      setConnections(canvasData.connections || []);
    }
  };

  const provisionAll = async () => {
    const { currentOrganization } = JSON.parse(
      localStorage.getItem("persist:root") || "{}",
    );
    const orgId = currentOrganization?.currentOrganization?.id;

    if (!orgId) {
      alert("Please select an organization first.");
      return;
    }

    for (const item of canvasItems) {
      setProvisioningStatus((prev) => ({ ...prev, [item.id]: "provisioning" }));

      try {
        let endpoint;
        let payload;

        switch (item.type) {
          case "vm":
            endpoint = "/api/resources/vms";
            payload = {
              name: item.name,
              instance_type: "t2.micro",
              vcpu: 1,
              memory: 1,
              organization_id: orgId,
            };
            break;
          case "database":
            endpoint = "/api/resources/databases";
            payload = {
              name: item.name,
              engine: "postgresql",
              instance_class: "db.t2.micro",
              organization_id: orgId,
            };
            break;
          case "storage":
            endpoint = "/api/resources/storage";
            payload = {
              name: item.name,
              size_gb: 10,
              organization_id: orgId,
            };
            break;
          default:
            setProvisioningStatus((prev) => ({
              ...prev,
              [item.id]: "skipped",
            }));
            continue;
        }

        await axios.post(endpoint, payload);
        setProvisioningStatus((prev) => ({ ...prev, [item.id]: "running" }));
      } catch (error) {
        console.error("Provisioning error:", error);
        setProvisioningStatus((prev) => ({ ...prev, [item.id]: "failed" }));
      }
    }

    alert("Your architecture is live! Go to Resources to see metrics.");
  };

  const getItemPosition = (itemId) => {
    const item = canvasItems.find((i) => i.id === itemId);
    return item ? { x: item.x + 60, y: item.y + 40 } : null;
  };

  return (
    <div className="h-screen flex flex-col bg-gray-50 dark:bg-gray-900">
      {/* Top Toolbar */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3 flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900 dark:text-white">
          Architecture Canvas
        </h1>
        <div className="flex items-center gap-3">
          <select
            onChange={(e) => loadTemplate(e.target.value)}
            className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm"
          >
            <option value="">Load Template...</option>
            <option value="basic-web-app">Basic Web App</option>
            <option value="high-availability">High Availability Setup</option>
            <option value="static-website">Static Website</option>
          </select>
          <button
            onClick={loadSavedCanvas}
            className="px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg text-sm hover:bg-gray-200 dark:hover:bg-gray-600 flex items-center gap-2"
          >
            <DocumentArrowDownIcon className="w-4 h-4" />
            Load Saved
          </button>
          <button
            onClick={saveCanvas}
            className="px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg text-sm hover:bg-gray-200 dark:hover:bg-gray-600"
          >
            Save Architecture
          </button>
          <button
            onClick={clearCanvas}
            className="px-3 py-2 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded-lg text-sm hover:bg-red-200 dark:hover:bg-red-900/50 flex items-center gap-2"
          >
            <TrashIcon className="w-4 h-4" />
            Clear Canvas
          </button>
          <button
            onClick={provisionAll}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg text-sm hover:bg-primary-700 flex items-center gap-2"
          >
            <PlayIcon className="w-4 h-4" />
            Provision All
          </button>
          <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-700 rounded-lg px-2">
            <button
              onClick={handleZoomOut}
              className="p-1 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
              title="Zoom Out"
            >
              <span className="text-lg font-bold">−</span>
            </button>
            <span className="text-sm text-gray-700 dark:text-gray-300 min-w-[50px] text-center">
              {zoom}%
            </span>
            <button
              onClick={handleZoomIn}
              className="p-1 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
              title="Zoom In"
            >
              <span className="text-lg font-bold">+</span>
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 flex">
        {/* Left Palette */}
        <div className="w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 p-4 overflow-y-auto">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">
            Components
          </h2>
          <div className="space-y-2">
            {PALETTE_ITEMS.map((item) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.id}
                  draggable
                  onDragStart={(e) => handleDragStart(e, item)}
                  className="p-3 bg-gray-50 dark:bg-gray-700 rounded-lg cursor-grab hover:bg-gray-100 dark:hover:bg-gray-600 border border-gray-200 dark:border-gray-600"
                >
                  <div className="flex items-center gap-3">
                    <Icon className="w-6 h-6 text-primary-600 dark:text-primary-400" />
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-white">
                        {item.name}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {item.awsEquivalent}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Canvas */}
        <div className="flex-1 relative overflow-hidden">
          <div
            ref={canvasRef}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            onWheel={handleWheel}
            className="w-full h-full bg-white dark:bg-gray-900"
            style={{
              backgroundImage:
                "radial-gradient(circle, #d1d5db 1px, transparent 1px)",
              backgroundSize: "20px 20px",
              transform: `scale(${zoom / 100})`,
              transformOrigin: "top left",
            }}
          >
            {/* SVG Connections */}
            <svg className="absolute inset-0 w-full h-full pointer-events-none">
              {connections.map((conn, index) => {
                const fromPos = getItemPosition(conn.from);
                const toPos = getItemPosition(conn.to);
                if (!fromPos || !toPos) return null;

                // Elbow routing: horizontal -> vertical -> horizontal
                const midX = (fromPos.x + toPos.x) / 2;
                const pathD = `M ${fromPos.x} ${fromPos.y} L ${midX} ${fromPos.y} L ${midX} ${toPos.y} L ${toPos.x} ${toPos.y}`;

                return (
                  <g key={index}>
                    <path
                      d={pathD}
                      stroke="#6366f1"
                      strokeWidth="2"
                      fill="none"
                    />
                    <rect
                      x={midX - 35}
                      y={(fromPos.y + toPos.y) / 2 - 10}
                      width="70"
                      height="20"
                      fill="white"
                      rx="4"
                    />
                    <text
                      x={midX}
                      y={(fromPos.y + toPos.y) / 2 + 4}
                      textAnchor="middle"
                      fontSize="10"
                      fill="#6366f1"
                    >
                      {conn.label}
                    </text>
                  </g>
                );
              })}
            </svg>

            {/* Canvas Items */}
            {canvasItems.map((item) => {
              const Icon = getItemIcon(item.type);
              const status = provisioningStatus[item.id] || item.status;
              const isSelected = selectedItem === item.id;
              const isConnectionSource = connectionMode?.from === item.id;

              return (
                <div
                  key={item.id}
                  onClick={() => handleItemClick(item)}
                  className={`absolute cursor-pointer transition-all ${
                    isSelected
                      ? "ring-2 ring-primary-500 ring-offset-2"
                      : isConnectionSource
                        ? "ring-2 ring-success-500 ring-offset-2"
                        : ""
                  }`}
                  style={{ left: item.x, top: item.y }}
                >
                  <div
                    className={`w-32 p-3 bg-white dark:bg-gray-800 rounded-lg shadow-md border-2 ${
                      status === "running"
                        ? "border-success-500"
                        : status === "provisioning"
                          ? "border-warning-500"
                          : status === "failed"
                            ? "border-danger-500"
                            : "border-gray-300 dark:border-gray-600"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <Icon className="w-8 h-8 text-primary-600 dark:text-primary-400" />
                      <div className="flex gap-1">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            startConnection(item.id);
                          }}
                          className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                          title="Connect"
                        >
                          <PlusIcon className="w-4 h-4 text-gray-500" />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteItem(item.id);
                          }}
                          className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                          title="Delete"
                        >
                          <TrashIcon className="w-4 h-4 text-gray-500" />
                        </button>
                      </div>
                    </div>
                    <p className="text-xs font-medium text-gray-900 dark:text-white truncate">
                      {item.name}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {PALETTE_ITEMS.find((p) => p.type === item.type)?.name}
                    </p>
                    <div className="mt-2 flex items-center gap-2">
                      <div
                        className={`w-2 h-2 rounded-full ${
                          status === "running"
                            ? "bg-success-500"
                            : status === "provisioning"
                              ? "bg-warning-500 animate-pulse"
                              : status === "failed"
                                ? "bg-danger-500"
                                : "bg-gray-400"
                        }`}
                      />
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {status === "running"
                          ? "Running"
                          : status === "provisioning"
                            ? "Provisioning..."
                            : status === "failed"
                              ? "Failed"
                              : "Not provisioned"}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}

            {/* Item Info Popup */}
            {itemInfoPopup && (
              <div
                className="absolute bg-white dark:bg-gray-800 p-3 rounded-lg shadow-lg border border-gray-200 dark:border-gray-600 z-10 w-56"
                style={{ left: itemInfoPopup.x, top: itemInfoPopup.y }}
              >
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-semibold text-sm text-gray-900 dark:text-white">
                    {itemInfoPopup.paletteItem.name}
                  </h4>
                  <button
                    onClick={() => setItemInfoPopup(null)}
                    className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                  >
                    <XMarkIcon className="w-4 h-4" />
                  </button>
                </div>
                <div className="space-y-1 text-xs text-gray-600 dark:text-gray-300">
                  <p>
                    <span className="font-medium">AWS:</span>{" "}
                    {itemInfoPopup.paletteItem.awsEquivalent}
                  </p>
                  <p>
                    <span className="font-medium">Cost:</span>{" "}
                    {itemInfoPopup.paletteItem.cost}
                  </p>
                </div>
                <button
                  onClick={() => {
                    setLearningContent({
                      type: "item-added",
                      ...itemInfoPopup.paletteItem,
                    });
                    setLearningPanelOpen(true);
                    setItemInfoPopup(null);
                  }}
                  className="mt-2 text-xs text-primary-600 dark:text-primary-400 hover:underline"
                >
                  Learn more →
                </button>
              </div>
            )}

            {connectionMode && (
              <div className="absolute top-4 left-4 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 px-4 py-2 rounded-lg text-sm">
                Click another item to connect
                <button
                  onClick={() => setConnectionMode(null)}
                  className="ml-2 hover:text-blue-900 dark:hover:text-blue-300"
                >
                  <XMarkIcon className="w-4 h-4 inline" />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Learning Panel */}
        {learningPanelOpen && (
          <div className="w-80 bg-white dark:bg-gray-800 border-l border-gray-200 dark:border-gray-700 p-4 overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
                Learning Panel
              </h2>
              <button
                onClick={() => setLearningPanelOpen(false)}
                className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              >
                <XMarkIcon className="w-5 h-5" />
              </button>
            </div>

            {learningContent ? (
              <div className="space-y-4">
                {learningContent.type === "item-added" && (
                  <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg">
                    <h3 className="font-medium text-blue-900 dark:text-blue-100 mb-2">
                      You added: {learningContent.name}
                    </h3>
                    <div className="space-y-2 text-sm text-blue-800 dark:text-blue-200">
                      <p>
                        <strong>AWS Equivalent:</strong>{" "}
                        {learningContent.awsEquivalent}
                      </p>
                      <p>
                        <strong>This costs:</strong> {learningContent.cost}
                      </p>
                      <p>
                        <strong>Real use:</strong> {learningContent.realUse}
                      </p>
                    </div>
                  </div>
                )}

                {learningContent.type === "connection-added" && (
                  <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg">
                    <h3 className="font-medium text-green-900 dark:text-green-100 mb-2">
                      You connected: {learningContent.from?.name} →{" "}
                      {learningContent.to?.name}
                    </h3>
                    <div className="space-y-2 text-sm text-green-800 dark:text-green-200">
                      <p>
                        <strong>Connection type:</strong>{" "}
                        {learningContent.label}
                      </p>
                      <p>
                        <strong>In AWS:</strong> Resources communicate via VPC
                        networking
                      </p>
                      {learningContent.label === "DB Connection" && (
                        <p>
                          <strong>Best practice:</strong> Put DB in private
                          subnet, not public
                        </p>
                      )}
                    </div>
                  </div>
                )}

                {learningContent.type === "template-loaded" && (
                  <div className="bg-purple-50 dark:bg-purple-900/20 p-4 rounded-lg">
                    <h3 className="font-medium text-purple-900 dark:text-purple-100 mb-2">
                      Template: {learningContent.name}
                    </h3>
                    <p className="text-sm text-purple-800 dark:text-purple-200">
                      {learningContent.description}
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-sm text-gray-500 dark:text-gray-400">
                <p>Drag items from the palette to the canvas.</p>
                <p className="mt-2">
                  Click the + button on items to connect them.
                </p>
                <p className="mt-2">Use templates to learn common patterns.</p>
              </div>
            )}
          </div>
        )}

        {!learningPanelOpen && (
          <button
            onClick={() => setLearningPanelOpen(true)}
            className="absolute right-4 top-4 bg-white dark:bg-gray-800 p-2 rounded-lg shadow-md border border-gray-200 dark:border-gray-700"
          >
            <PlusIcon className="w-5 h-5 text-gray-600 dark:text-gray-400" />
          </button>
        )}
      </div>
    </div>
  );
};

export default ArchitectureCanvas;
