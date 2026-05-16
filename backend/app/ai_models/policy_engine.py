"""Rules-based governance policy compiler for the simulator."""

from __future__ import annotations

import re


class PolicyEngine:
    """Compile explicit policy rules into executable simulation rules.

    The governance module is intentionally rules-based. It does not infer
    meaning from free-form policy language. Instead, it accepts a small
    structured syntax such as:

    - resource_type=database; encryption=required; public_access=deny
    - resource_type=vm; max_cpu=70; max_memory=80; tag=Environment:Production
    """

    def parse_policy(self, policy_rule):
        rule_text = (policy_rule or '').strip()
        if not rule_text:
            return {'success': False, 'error': 'Policy rule is required'}

        compiled = self._compile_explicit_rule(rule_text)
        if not compiled['fields']:
            compiled = self._compile_natural_language_rule(rule_text)
        if not compiled['fields']:
            return {
                'success': False,
                'error': (
                    'Use explicit key=value rules or simple natural language such as '
                    '"all databases must be encrypted", '
                    '"all VMs must have tag Environment:Production", or '
                    '"VM names must start with web-".'
                ),
            }

        return {
            'success': True,
            'confidence': 1.0,
            'parsed_rule': compiled,
        }

    def _compile_explicit_rule(self, rule_text):
        tokens = [token.strip() for token in re.split(r'[;\n,]+', rule_text) if token.strip()]
        fields = {}
        required_tags = []
        matched_any = False

        for token in tokens:
            if '=' not in token:
                continue
            key, value = [part.strip() for part in token.split('=', 1)]
            normalized_key = key.lower().replace(' ', '_')
            normalized_value = value.strip()
            matched_any = True

            if normalized_key in {'resource_type', 'type'}:
                fields['resource_type'] = normalized_value.lower()
            elif normalized_key in {'encryption', 'storage_encryption'}:
                fields['requires_encryption'] = normalized_value.lower() in {'required', 'true', 'yes', 'on'}
            elif normalized_key in {'public_access', 'public'}:
                fields['requires_public_block'] = normalized_value.lower() in {'deny', 'blocked', 'false', 'no', 'off'}
                fields['requires_private_access'] = fields['requires_public_block']
            elif normalized_key in {'tag', 'tags', 'required_tag'}:
                if ':' in normalized_value:
                    tag_key, tag_value = [part.strip() for part in normalized_value.split(':', 1)]
                    required_tags.append({'key': tag_key, 'value': tag_value})
                else:
                    required_tags.append({'key': normalized_value, 'value': normalized_value})
            elif normalized_key in {'max_cpu', 'cpu'}:
                fields['max_cpu'] = self._to_float(normalized_value)
            elif normalized_key in {'max_memory', 'memory'}:
                fields['max_memory'] = self._to_float(normalized_value)
            elif normalized_key in {'max_network', 'network'}:
                fields['max_network'] = self._to_float(normalized_value)
            elif normalized_key in {'name_prefix', 'required_name_prefix'}:
                fields['required_name_prefix'] = normalized_value
                fields.setdefault('type', 'naming')
            elif normalized_key in {'name_regex', 'required_name_regex', 'name_pattern'}:
                fields['required_name_regex'] = normalized_value
                fields.setdefault('type', 'naming')
            elif normalized_key in {'severity'}:
                fields['severity'] = normalized_value.lower()
            elif normalized_key in {'policy_type', 'type_hint'}:
                fields['type'] = normalized_value.lower()

        if required_tags:
            fields['required_tags'] = required_tags

        if not matched_any and not required_tags:
            return {
                'expression': rule_text,
                'fields': {},
            }

        fields.setdefault('type', 'custom')
        fields.setdefault('severity', 'medium')
        fields.setdefault('resource_type', None)
        fields.setdefault('requires_encryption', False)
        fields.setdefault('requires_private_access', False)
        fields.setdefault('requires_public_block', False)
        fields.setdefault('required_tags', [])
        fields.setdefault('max_cpu', None)
        fields.setdefault('max_memory', None)
        fields.setdefault('max_network', None)
        fields.setdefault('required_name_prefix', None)
        fields.setdefault('required_name_regex', None)

        return {
            'expression': rule_text,
            'fields': fields,
        }

    def _compile_natural_language_rule(self, rule_text):
        lowered = " ".join((rule_text or "").strip().lower().split())
        fields = {}
        required_tags = []

        resource_match = re.search(
            r'\b(all\s+)?(?P<resource>virtual machines|virtual machine|vms|vm|databases|database|dbs|db|resources|resource)\b',
            lowered,
        )
        if resource_match:
            resource = resource_match.group('resource')
            fields['resource_type'] = self._normalize_resource_type(resource)

        if re.search(r'\b(encrypt|encrypted)\b', lowered):
            fields['requires_encryption'] = True
            fields.setdefault('type', 'security')

        if re.search(r'\b(not\s+be|not\s+become|be)\s+publicly\s+accessible\b', lowered):
            fields['requires_public_block'] = True
            fields['requires_private_access'] = True
            fields.setdefault('type', 'security')

        tag_match = re.search(
            r'\bmust\s+have\s+tag\s+(?P<key>[a-z0-9_.-]+)(?:\s*[:=]\s*(?P<value>[a-z0-9_.-]+))?\b',
            lowered,
        )
        if tag_match:
            required_tags.append(
                {
                    'key': tag_match.group('key'),
                    'value': tag_match.group('value') or '',
                }
            )
            fields.setdefault('type', 'tagging')

        prefix_match = re.search(
            r'\bname(?:s)?\s+must\s+start\s+with\s+(?P<prefix>[^\s;,]+)',
            lowered,
        )
        if prefix_match:
            fields['required_name_prefix'] = prefix_match.group('prefix')
            fields.setdefault('type', 'naming')

        regex_match = re.search(
            r'\bname(?:s)?\s+must\s+match\s+(?P<pattern>.+)$',
            lowered,
        )
        if regex_match:
            fields['required_name_regex'] = regex_match.group('pattern').strip().strip('"\'')
            fields.setdefault('type', 'naming')

        if required_tags:
            fields['required_tags'] = required_tags

        if not fields:
            return {'expression': rule_text, 'fields': {}}

        fields.setdefault('type', 'compliance')
        fields.setdefault('severity', 'medium')
        fields.setdefault('resource_type', None)
        fields.setdefault('requires_encryption', False)
        fields.setdefault('requires_private_access', False)
        fields.setdefault('requires_public_block', False)
        fields.setdefault('required_tags', [])
        fields.setdefault('max_cpu', None)
        fields.setdefault('max_memory', None)
        fields.setdefault('max_network', None)
        fields.setdefault('required_name_prefix', None)
        fields.setdefault('required_name_regex', None)

        return {
            'expression': rule_text,
            'fields': fields,
        }

    def _to_float(self, value):
        try:
            return float(re.sub(r'[^0-9.\-]', '', value))
        except ValueError:
            return None

    def _normalize_resource_type(self, value):
        normalized = (value or '').strip().lower()
        if normalized in {'vm', 'vms', 'virtual machine', 'virtual machines'}:
            return 'vm'
        if normalized in {'database', 'databases', 'db', 'dbs'}:
            return 'database'
        return None

    def evaluate_resource(self, rule, resource):
        """Evaluate a compiled rule against a simulated resource."""
        violations = []
        resource_type = rule.get('resource_type')
        resource_kind = resource.get('resource_kind') or resource.get('type')
        if resource_type and resource_kind and resource_type != resource_kind:
            return {'compliant': True, 'violations': [], 'rule': rule, 'resource': resource}

        if rule.get('requires_encryption') and not resource.get('storage_encrypted', False):
            violations.append('Resource storage must be encrypted')

        public_accessible = resource.get('publicly_accessible')
        if public_accessible is None:
            public_accessible = bool(resource.get('public_ip')) or resource.get('subnet_type') == 'public'
        if rule.get('requires_public_block') and public_accessible:
            violations.append('Public access must be disabled')

        if rule.get('required_tags'):
            current_tags = {tag.get('key', '').lower(): tag.get('value', '') for tag in resource.get('tags', [])}
            current_tag_values = {value.lower() for value in current_tags.values()}
            for tag in rule['required_tags']:
                tag_key = (tag.get('key') or '').lower()
                tag_value = (tag.get('value') or '').lower()
                if tag_key in current_tags:
                    if tag_value and current_tags.get(tag_key, '').lower() != tag_value:
                        violations.append(f"Required tag value mismatch: {tag['key']}={tag['value']}")
                elif tag_value not in current_tag_values and tag_key not in current_tag_values:
                    violations.append(f"Required tag missing: {tag['key']}")

        name_prefix = rule.get('required_name_prefix')
        if name_prefix:
            resource_name = str(resource.get('name') or '')
            if not resource_name.lower().startswith(str(name_prefix).lower()):
                violations.append(f"Name must start with {name_prefix}")

        name_regex = rule.get('required_name_regex')
        if name_regex:
            resource_name = str(resource.get('name') or '')
            try:
                if not re.search(name_regex, resource_name):
                    violations.append(f"Name must match pattern {name_regex}")
            except re.error:
                violations.append(f"Invalid name pattern {name_regex}")

        cpu_limit = rule.get('max_cpu')
        if cpu_limit is not None and resource.get('cpu_utilization', 0) > cpu_limit:
            violations.append(f"CPU utilization exceeds {cpu_limit}%")

        memory_limit = rule.get('max_memory')
        if memory_limit is not None and resource.get('memory_utilization', 0) > memory_limit:
            violations.append(f"Memory utilization exceeds {memory_limit}%")

        network_limit = rule.get('max_network')
        if network_limit is not None:
            network_value = max(
                resource.get('network_in_mbps', 0) or 0,
                resource.get('network_out_mbps', 0) or 0,
            )
            if network_value > network_limit:
                violations.append(f"Network throughput exceeds {network_limit}")

        return {
            'compliant': len(violations) == 0,
            'violations': violations,
            'rule': rule,
            'resource': resource,
        }


policy_engine = PolicyEngine()
