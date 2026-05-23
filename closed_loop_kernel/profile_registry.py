from __future__ import annotations

import json
from pathlib import Path


REQUIRED_POLICY_KEYS = [
    "readable_inputs",
    "writable_outputs",
    "record_required",
    "machine_record_required",
    "source_refs_required",
    "artifact_refs_required",
    "memory_candidate_allowed",
    "promoted_memory_allowed",
    "cleanup_required",
    "required_fields",
    "sensitivity_level",
    "retention_policy",
    "cleanup_lifecycle_state",
]

REQUIRED_ENVELOPE_FIELDS = [
    "task_id",
    "run_id",
    "profile_id",
    "source_refs",
    "artifact_refs",
    "content_hash",
    "created_at",
    "sensitivity",
    "retention_policy",
    "machine_record",
]


class ProfileRegistryError(Exception):
    """Exception raised for errors within the agent profile registry validation."""


class AgentProfileRegistry:
    """Agent Profile Registry for AI-native company operating system kernel."""

    def __init__(self, profiles: list[dict]):
        self.profiles = profiles
        self._profiles_by_id = {p["profile_id"]: p for p in profiles}

    @classmethod
    def from_path(cls, path: str | Path) -> "AgentProfileRegistry":
        """Loads and instantiates AgentProfileRegistry from a JSON file path."""
        try:
            with Path(path).open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise ProfileRegistryError(f"Failed to load registry JSON: {e}")

        profiles = data.get("profiles", [])
        return cls(profiles)

    def validate(self) -> None:
        """Validates all registered profiles in the seed schema."""
        if len(self._profiles_by_id) != len(self.profiles):
            raise ProfileRegistryError("profile_id values must be unique")

        for profile in self.profiles:
            profile_id = profile.get("profile_id")
            if not profile_id:
                raise ProfileRegistryError("Profile entry is missing required field: 'profile_id'")
            if "permanence_level" not in profile:
                raise ProfileRegistryError(f"Profile '{profile_id}' is missing required field: 'permanence_level'")
            if profile["permanence_level"] not in {"permanent", "dynamic"}:
                raise ProfileRegistryError(f"Profile '{profile_id}' has invalid permanence_level")

            policy = profile.get("data_flow_policy")
            if not policy:
                raise ProfileRegistryError(f"Profile '{profile_id}' is missing required data_flow_policy")

            for key in REQUIRED_POLICY_KEYS:
                if key not in policy:
                    raise ProfileRegistryError(
                        f"data_flow_policy of profile '{profile_id}' is missing required key: '{key}'"
                    )
            for key in ["readable_inputs", "writable_outputs", "required_fields"]:
                if not isinstance(policy[key], list) or not policy[key]:
                    raise ProfileRegistryError(f"data_flow_policy.{key} must be a non-empty list for '{profile_id}'")
            missing_required_fields = sorted(set(REQUIRED_ENVELOPE_FIELDS) - set(policy["required_fields"]))
            if missing_required_fields:
                raise ProfileRegistryError(
                    f"data_flow_policy.required_fields missing {missing_required_fields} for '{profile_id}'"
                )

    def permanent_profile_ids(self) -> list[str]:
        """Returns the list of permanent profile IDs in seed order."""
        return [p["profile_id"] for p in self.profiles if p.get("permanence_level") == "permanent"]

    def dynamic_profile_ids(self) -> list[str]:
        """Returns the list of dynamic profile IDs in seed order."""
        return [p["profile_id"] for p in self.profiles if p.get("permanence_level") == "dynamic"]

    def get_profile(self, profile_id: str) -> dict:
        """Retrieves profile definition by its ID."""
        profile = self._profiles_by_id.get(profile_id)
        if not profile:
            raise ProfileRegistryError(f"Profile '{profile_id}' not found in registry")
        return profile

    def validate_output_envelope(self, profile_id: str, envelope: dict) -> None:
        """Validates a given agent output envelope structure against profile policies."""
        env_profile_id = envelope.get("profile_id")
        if env_profile_id != profile_id:
            raise ProfileRegistryError(
                f"Envelope profile_id '{env_profile_id}' does not match expected profile_id '{profile_id}'"
            )

        profile = self.get_profile(profile_id)
        policy = profile.get("data_flow_policy", {})

        for field in policy.get("required_fields", REQUIRED_ENVELOPE_FIELDS):
            if field not in envelope:
                raise ProfileRegistryError(f"Envelope is missing required field: '{field}'")

        if not envelope.get("source_refs"):
            raise ProfileRegistryError("Envelope source_refs must not be empty")
        if not envelope.get("artifact_refs"):
            raise ProfileRegistryError("Envelope artifact_refs must not be empty")

        output_type = envelope.get("output_type")
        if not output_type:
            raise ProfileRegistryError("Envelope is missing required field: 'output_type'")

        writable_outputs = policy.get("writable_outputs", [])
        if output_type not in writable_outputs:
            raise ProfileRegistryError(
                f"Output type '{output_type}' is not allowed for profile '{profile_id}'. Allowed: {writable_outputs}"
            )

        if "promoted_memory" in envelope:
            promoted_memory_allowed = policy.get("promoted_memory_allowed", False)
            if not promoted_memory_allowed:
                raise ProfileRegistryError("promoted memory is not allowed for this profile")

    def validate_role_isolation(self, isolation: dict) -> None:
        """Validates separation of duties and profile role assignment isolation constraint rules."""
        operation = isolation.get("operation")
        if operation == "profile_update":
            executor = isolation.get("executor_profile")
            maintainer = isolation.get("maintainer_profile")
            verifier = isolation.get("verifier_profile")
            reviewer = isolation.get("reviewer_profile")

            if executor == reviewer:
                raise ProfileRegistryError("self-review is not allowed: executor cannot review their own work")

            roles = []
            if maintainer:
                roles.append(("maintainer_profile", maintainer))
            if verifier:
                roles.append(("verifier_profile", verifier))
            if reviewer:
                roles.append(("reviewer_profile", reviewer))

            seen_profiles = {}
            for role_name, p_id in roles:
                if p_id in seen_profiles:
                    raise ProfileRegistryError(
                        f"Duplicate assignment: '{p_id}' is assigned to both '{seen_profiles[p_id]}' and '{role_name}'"
                    )
                seen_profiles[p_id] = role_name
