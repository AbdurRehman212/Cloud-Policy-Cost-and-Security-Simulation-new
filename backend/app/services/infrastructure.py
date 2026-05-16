"""Module 1 — Infrastructure topology service.

CloudSim-style Datacenter → Host → VM hierarchy, derived deterministically from
existing VMs without altering DB schema. Safe, additive, O(N) per build.

Design notes
------------
* Topology is derived on demand from running VMs in an organization.
* Hosts are pooled per (organization, subnet). Each Host is a bin-packed
  container of VMs whose combined vCPU and RAM fit the host's capacity.
* Datacenters group hosts per organization. A single default datacenter is
  created per org; larger orgs can later be split across datacenters without
  breaking the contract returned by `build_topology`.

No database changes are required; the derivation is deterministic, cached per
simulator tick via an in-memory snapshot dict if desired by callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.models.resources import ResourceStatus, VirtualMachine


# ── Host capacity templates (bin-packing target size) ────────────────────────
# Standard physical host sizes — tuned so that ~3–8 small VMs fit per host.
_HOST_TEMPLATES = [
    {"name": "host-small",  "cpu_cores": 8,  "memory_gb": 32.0},
    {"name": "host-medium", "cpu_cores": 16, "memory_gb": 64.0},
    {"name": "host-large",  "cpu_cores": 32, "memory_gb": 128.0},
]
_DEFAULT_HOST = _HOST_TEMPLATES[1]  # medium


@dataclass
class Host:
    """Logical host aggregating a subset of VMs.

    Capacity tracking is derived from attached VMs. `used_*` are computed
    live so we never drift out of sync with the source VM records.
    """
    id: str                           # synthetic: f"h-{org_id}-{idx}"
    name: str
    datacenter_id: str
    cpu_cores: int
    memory_gb: float
    vms: list[VirtualMachine] = field(default_factory=list)

    @property
    def used_vcpu(self) -> int:
        return sum(int(vm.vcpu or 1) for vm in self.vms)

    @property
    def used_memory_gb(self) -> float:
        return sum(float(vm.memory_gb or 0) for vm in self.vms)

    @property
    def cpu_avg(self) -> float:
        """Weighted CPU average across assigned VMs (0–100)."""
        total_vcpu = self.used_vcpu
        if total_vcpu <= 0 or not self.vms:
            return 0.0
        weighted = sum(
            float(vm.cpu_utilization or 0) * float(vm.vcpu or 1) for vm in self.vms
        )
        return max(0.0, min(100.0, weighted / total_vcpu))

    @property
    def memory_avg(self) -> float:
        if not self.vms:
            return 0.0
        avg = sum(float(vm.memory_utilization or 0) for vm in self.vms) / len(self.vms)
        return max(0.0, min(100.0, avg))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "datacenter_id": self.datacenter_id,
            "cpu_cores": self.cpu_cores,
            "memory_gb": self.memory_gb,
            "used_vcpu": self.used_vcpu,
            "used_memory_gb": round(self.used_memory_gb, 2),
            "cpu_avg": round(self.cpu_avg, 2),
            "memory_avg": round(self.memory_avg, 2),
            "vm_count": len(self.vms),
            "vm_ids": [vm.id for vm in self.vms],
        }


@dataclass
class Datacenter:
    id: str                           # synthetic: f"dc-{org_id}"
    name: str
    organization_id: int
    hosts: list[Host] = field(default_factory=list)

    @property
    def total_cpu_cores(self) -> int:
        return sum(h.cpu_cores for h in self.hosts)

    @property
    def total_memory_gb(self) -> float:
        return sum(h.memory_gb for h in self.hosts)

    @property
    def cpu_avg(self) -> float:
        """Aggregate CPU across the whole datacenter (Module 1 §5)."""
        total_vcpu = sum(h.used_vcpu for h in self.hosts)
        if total_vcpu <= 0:
            return 0.0
        weighted = sum(h.cpu_avg * h.used_vcpu for h in self.hosts)
        return max(0.0, min(100.0, weighted / total_vcpu))

    @property
    def memory_avg(self) -> float:
        vms = [vm for h in self.hosts for vm in h.vms]
        if not vms:
            return 0.0
        avg = sum(float(vm.memory_utilization or 0) for vm in vms) / len(vms)
        return max(0.0, min(100.0, avg))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "organization_id": self.organization_id,
            "total_cpu_cores": self.total_cpu_cores,
            "total_memory_gb": round(self.total_memory_gb, 2),
            "cpu_avg": round(self.cpu_avg, 2),
            "memory_avg": round(self.memory_avg, 2),
            "host_count": len(self.hosts),
            "hosts": [h.to_dict() for h in self.hosts],
        }


def _bin_pack_vms_into_hosts(org_id: int, dc_id: str, vms: Iterable[VirtualMachine]) -> list[Host]:
    """First-fit-decreasing bin packing of VMs onto host templates.

    Deterministic: sorted by vCPU desc then id asc. No randomness.
    """
    sorted_vms = sorted(vms, key=lambda v: (-(v.vcpu or 1), v.id))
    hosts: list[Host] = []
    idx = 0
    for vm in sorted_vms:
        need_vcpu = int(vm.vcpu or 1)
        need_mem = float(vm.memory_gb or 0)
        placed = False
        for host in hosts:
            if (host.used_vcpu + need_vcpu) <= host.cpu_cores and \
               (host.used_memory_gb + need_mem) <= host.memory_gb:
                host.vms.append(vm)
                placed = True
                break
        if not placed:
            tpl = _DEFAULT_HOST if need_vcpu <= 16 else _HOST_TEMPLATES[2]
            host = Host(
                id=f"h-{org_id}-{idx}",
                name=f"{tpl['name']}-{idx}",
                datacenter_id=dc_id,
                cpu_cores=int(tpl["cpu_cores"]),
                memory_gb=float(tpl["memory_gb"]),
            )
            host.vms.append(vm)
            hosts.append(host)
            idx += 1
    return hosts


def build_topology(org_id: int) -> Datacenter:
    """Return a deterministic Datacenter → Host → VM view for the org.

    Only non-terminated VMs are included. Terminated VMs are excluded so the
    topology reflects live capacity.
    """
    vms = (
        VirtualMachine.query
        .filter(VirtualMachine.organization_id == org_id)
        .filter(VirtualMachine.status != ResourceStatus.TERMINATED)
        .all()
    )
    dc_id = f"dc-{org_id}"
    dc = Datacenter(
        id=dc_id,
        name=f"datacenter-{org_id}",
        organization_id=org_id,
        hosts=_bin_pack_vms_into_hosts(org_id, dc_id, vms),
    )
    return dc


def aggregate_via_topology(org_id: int) -> dict:
    """Module 1 §5: cpu_avg/memory_avg computed VM → Host → Datacenter.

    Returns compact metrics plus the full nested topology dict.
    """
    dc = build_topology(org_id)
    return {
        "cpu_avg": round(dc.cpu_avg, 2),
        "memory_avg": round(dc.memory_avg, 2),
        "host_count": len(dc.hosts),
        "vm_count": sum(len(h.vms) for h in dc.hosts),
        "topology": dc.to_dict(),
    }
