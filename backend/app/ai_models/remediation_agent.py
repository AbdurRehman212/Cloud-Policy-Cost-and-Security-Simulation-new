"""Remediation Agent decision rules (Module 10).

This is a deterministic, rule-based recommender — it is NOT a trained model. An earlier
version carried an untrained "Q-table" that never changed the ranking; it was removed so
the module does not present rules as learned behaviour. Every recommendation carries the
rule that produced it, so the output is explainable to a learner.

The agent only *proposes* actions. Execution, verification and state changes are done by
``app.services.remediation_service`` against simulated resources inside this application.
"""

from __future__ import annotations

# A threat below this confidence is not acted on automatically; a human reviews it.
REVIEW_CONFIDENCE_THRESHOLD = 0.75
IDLE_CPU_THRESHOLD = 10.0  # percent

# Actions that change resource configuration or availability need explicit approval.
APPROVAL_REQUIRED = {
    'isolate_resource', 'block_ip', 'scale_up', 'disable_public_access',
    'enable_encryption', 'stop_idle_resource', 'downsize_resource', 'add_required_tag',
}

ACTION_CATALOG = {
    'isolate_resource': {
        'label': 'Isolate resource',
        'description': 'Detach the resource from its security groups and attach a quarantine group that denies all inbound traffic.',
        'consequence': 'All inbound traffic to the resource stops until the original security groups are restored.',
        'recovery': 'After the investigation, re-attach the original security groups listed in this action (Resources → Security groups).',
        'targets': {'vm'},
    },
    'block_ip': {
        'label': 'Block source IP',
        'description': 'Add an inbound DENY rule for the attacking source address to the resource\'s security groups.',
        'consequence': 'Traffic from that address is dropped; legitimate users sharing the address are also blocked.',
        'recovery': 'Delete the DENY rule from the security group once the source is no longer hostile.',
        'targets': {'vm', 'organization'},
    },
    'scale_up': {
        'label': 'Scale up capacity',
        'description': 'Resize the instance to the next larger type so it can absorb the traffic spike.',
        'consequence': 'Hourly cost increases to the larger instance price.',
        'recovery': 'Resize back to the original type when traffic returns to normal.',
        'targets': {'vm'},
    },
    'disable_public_access': {
        'label': 'Disable public access',
        'description': 'Turn off public accessibility so the resource is reachable only from the private network.',
        'consequence': 'Clients connecting over the internet lose access.',
        'recovery': 'Re-enable public access only behind an approved, restricted security group.',
        'targets': {'database', 'vm'},
    },
    'enable_encryption': {
        'label': 'Enable storage encryption',
        'description': 'Enable encryption at rest for the resource\'s storage.',
        'consequence': 'Simulated brief maintenance; no data change.',
        'recovery': 'Encryption should stay enabled; no rollback is recommended.',
        'targets': {'database'},
    },
    'stop_idle_resource': {
        'label': 'Stop idle resource',
        'description': 'Stop the resource while it is idle so it stops accruing compute cost.',
        'consequence': 'The resource is unavailable until it is started again.',
        'recovery': 'Start the resource from the Resources page when it is needed.',
        'targets': {'vm'},
    },
    'downsize_resource': {
        'label': 'Downsize resource',
        'description': 'Resize the instance to the next smaller type to match its low utilization.',
        'consequence': 'Lower hourly cost; less headroom if load returns.',
        'recovery': 'Resize to the previous type if utilization rises.',
        'targets': {'vm'},
    },
    'add_required_tag': {
        'label': 'Add required tag',
        'description': 'Add the tag the policy requires to the resource.',
        'consequence': 'Tag metadata changes; no availability impact.',
        'recovery': 'Edit or remove the tag from the resource tags editor.',
        'targets': {'vm', 'database'},
    },
    'request_review': {
        'label': 'Request human review',
        'description': 'Record the issue for a person to investigate; no configuration is changed.',
        'consequence': 'The issue stays open until someone reviews it.',
        'recovery': 'Not applicable — nothing is changed.',
        'targets': {'vm', 'database', 'organization', None},
    },
}


def _threat_type(threat):
    return str((threat or {}).get('type') or (threat or {}).get('threat_type') or 'unknown').lower()


def _kind(resource):
    return (resource or {}).get('resource_kind') or (resource or {}).get('type')


class RemediationAgent:
    """Deterministic, explainable remediation rules."""

    action_space = list(ACTION_CATALOG)

    def recommend(self, threat=None, resource=None, violations=None):
        """Return an ordered list of ``{action, reason}`` recommendations.

        ``threat``: dict with type/confidence (None for governance or idle issues).
        ``resource``: resource dict (``to_dict()``), or None.
        ``violations``: policy-engine violation messages for a governance issue.
        """
        recs = []

        def add(action, reason):
            if action not in [r['action'] for r in recs]:
                recs.append({'action': action, 'reason': reason})

        if threat is not None:
            threat_type = _threat_type(threat)
            confidence = float(threat.get('confidence', 0.5) or 0.0)
            if confidence < REVIEW_CONFIDENCE_THRESHOLD:
                # Low confidence: do not change configuration on an uncertain detection.
                # Resource hygiene rules below still apply; they do not depend on the detection.
                add('request_review', f'Detection confidence {confidence:.2f} is below the {REVIEW_CONFIDENCE_THRESHOLD} action threshold.')
            elif threat_type not in {'ddos', 'brute_force', 'malware', 'port_scan'}:
                add('request_review', f'No containment playbook exists for threat type "{threat_type}".')
            else:
                if threat_type in {'ddos', 'brute_force', 'malware'}:
                    add('isolate_resource', f'High-confidence {threat_type} threat: contain the affected resource first.')
                if threat_type == 'ddos':
                    add('scale_up', 'A DDoS floods capacity; extra capacity keeps the service responsive while contained.')
                if threat_type in {'brute_force', 'port_scan'}:
                    add('block_ip', f'{threat_type} traffic comes from an identifiable source address.')

        for message in violations or []:
            text = str(message).lower()
            if 'encrypt' in text:
                add('enable_encryption', f'Policy violation: {message}.')
            elif 'public access' in text:
                add('disable_public_access', f'Policy violation: {message}.')
            elif 'required tag missing' in text or 'tag value mismatch' in text:
                add('add_required_tag', f'Policy violation: {message}.')
            elif 'cpu utilization exceeds' in text or 'memory utilization exceeds' in text:
                add('scale_up', f'Policy violation: {message}.')
            else:
                add('request_review', f'No safe automatic fix for: {message}.')

        if resource:
            kind = _kind(resource)
            if kind == 'database' and resource.get('publicly_accessible'):
                add('disable_public_access', 'The database is publicly accessible.')
            if kind == 'database' and resource.get('storage_encrypted') is False:
                add('enable_encryption', 'The database storage is not encrypted.')
            cpu = resource.get('cpu_utilization')
            status = str(resource.get('status') or 'running').lower()
            if kind in ('vm', None) and cpu is not None and float(cpu) < IDLE_CPU_THRESHOLD and status == 'running':
                add('stop_idle_resource', f'CPU utilization {float(cpu):.1f}% is below {IDLE_CPU_THRESHOLD:.0f}% (idle).')
                add('downsize_resource', 'An idle instance is over-provisioned; a smaller type costs less.')

        if not recs:
            add('request_review', 'No rule matched this issue; a person should decide.')
        return recs

    # ── Backwards-compatible API (used by older callers and Chapter 6 UT-50..54) ──
    def choose_actions(self, threat, resource):
        return [r['action'] for r in self.recommend(threat, resource)]

    def remediate(self, threat, resource):
        """Proposal only: nothing is executed here (status is ``proposed``)."""
        recs = self.recommend(threat, resource)
        return {
            'requires_approval': any(r['action'] in APPROVAL_REQUIRED for r in recs),
            'results': [
                {'action': r['action'], 'status': 'proposed', 'details': ACTION_CATALOG[r['action']]['description'], 'reason': r['reason']}
                for r in recs
            ],
            'recommendation': recs[0]['action'],
        }


remediation_agent = RemediationAgent()
