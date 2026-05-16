import { normalizeDashboardSnapshot } from "./dashboardSlice";

describe("normalizeDashboardSnapshot", () => {
  const baseSnapshot = {
    resources: { vms: { total: 2, running: 1 } },
    security: { active_threats: 0 },
    costs: { current_month_spend: 12.5 },
    workload: { queue_total_ms: 42 },
    snapshot_fresh: true,
  };

  it("accepts snapshots with org_id", () => {
    const result = normalizeDashboardSnapshot(
      { ...baseSnapshot, org_id: 7 },
      7,
    );

    expect(result).toMatchObject({
      org_id: 7,
      organization_id: 7,
      resources: baseSnapshot.resources,
      security: baseSnapshot.security,
      costs: baseSnapshot.costs,
    });
  });

  it("accepts snapshots with organization_id", () => {
    const result = normalizeDashboardSnapshot(
      { ...baseSnapshot, organization_id: 11 },
      11,
    );

    expect(result).toMatchObject({
      org_id: 11,
      organization_id: 11,
      resources: baseSnapshot.resources,
    });
  });

  it("preserves freshness metadata", () => {
    const result = normalizeDashboardSnapshot(
      {
        ...baseSnapshot,
        org_id: 5,
        snapshot_age_seconds: 3.25,
        snapshot_fresh: false,
      },
      5,
    );

    expect(result).toMatchObject({
      org_id: 5,
      organization_id: 5,
      snapshot_age_seconds: 3.25,
      snapshot_fresh: false,
    });
  });

  it("rejects partial invalidation payloads", () => {
    expect(
      normalizeDashboardSnapshot(
        { org_id: 3, organization_id: 3 },
        3,
      ),
    ).toBeNull();
  });
});
