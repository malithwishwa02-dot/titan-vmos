"""
Titan V11.3 — Device Property Validator
Validates system property consistency across apps.
Addresses GAP-SE3: Device property inconsistency.

Validates:
  - Property consistency across all apps
  - Property interdependencies
  - Validation against real device profiles
  - Cross-app property verification

Usage:
    validator = PropertyValidator(adb_target="127.0.0.1:5555")
    result = validator.validate_all_properties()
    if not result.passed:
        validator.fix_inconsistencies()
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("titan.property-validator")


@dataclass
class PropertyValidationResult:
    """Property validation result."""
    passed: bool = True
    total_checks: int = 0
    failed_checks: int = 0
    inconsistencies: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "total_checks": self.total_checks,
            "failed_checks": self.failed_checks,
            "inconsistencies": self.inconsistencies,
            "warnings": self.warnings,
        }


class PropertyValidator:
    """Validates device property consistency."""

    # Critical property groups that must be consistent
    PROPERTY_GROUPS = {
        "device_identity": [
            "ro.product.model",
            "ro.product.brand",
            "ro.product.manufacturer",
            "ro.product.device",
            "ro.product.name",
        ],
        "build_info": [
            "ro.build.fingerprint",
            "ro.build.id",
            "ro.build.version.release",
            "ro.build.version.sdk",
            "ro.build.type",
        ],
        "hardware": [
            "ro.hardware",
            "ro.board.platform",
            "ro.product.cpu.abi",
            "ro.product.cpu.abilist",
        ],
        "telephony": [
            "gsm.sim.operator.alpha",
            "gsm.sim.operator.numeric",
            "gsm.operator.alpha",
            "gsm.operator.numeric",
        ],
    }

    # Property interdependencies (property -> expected value based on other properties)
    PROPERTY_DEPENDENCIES = {
        "ro.product.model": {
            "samsung_s25_ultra": {
                "ro.product.brand": "samsung",
                "ro.product.manufacturer": "Samsung",
                "ro.product.device": "dm3q",
            },
            "google_pixel_9_pro": {
                "ro.product.brand": "google",
                "ro.product.manufacturer": "Google",
                "ro.product.device": "komodo",
            },
        },
    }

    def __init__(self, adb_target: str = "127.0.0.1:5555"):
        self.target = adb_target
        self._properties: Dict[str, str] = {}

    def validate_all_properties(self) -> PropertyValidationResult:
        """Validate all device properties for consistency."""
        result = PropertyValidationResult()

        # Load all properties
        self._load_properties()

        # Validate each property group
        for group_name, properties in self.PROPERTY_GROUPS.items():
            group_result = self._validate_property_group(group_name, properties)
            result.total_checks += 1
            if not group_result["passed"]:
                result.failed_checks += 1
                result.passed = False
                result.inconsistencies.append(group_result)

        # Validate property dependencies
        dep_result = self._validate_dependencies()
        result.total_checks += len(dep_result)
        for dep in dep_result:
            if not dep["passed"]:
                result.failed_checks += 1
                result.passed = False
                result.inconsistencies.append(dep)

        # Validate against real device profiles
        profile_result = self._validate_against_real_profiles()
        if profile_result["warnings"]:
            result.warnings.extend(profile_result["warnings"])

        logger.info(f"Property validation: {result.total_checks - result.failed_checks}/{result.total_checks} passed")
        return result

    def _load_properties(self):
        """Load all system properties from device."""
        from adb_utils import adb_shell as _adb_shell

        # Get all properties
        props_output = _adb_shell(self.target, "getprop")

        # Parse properties
        for line in props_output.split('\n'):
            if '[' in line and ']' in line:
                try:
                    # Format: [property.name]: [value]
                    parts = line.split(']: [')
                    if len(parts) == 2:
                        prop_name = parts[0].strip('[')
                        prop_value = parts[1].strip(']')
                        self._properties[prop_name] = prop_value
                except Exception:
                    continue

        logger.debug(f"Loaded {len(self._properties)} properties")

    def _validate_property_group(self, group_name: str, properties: List[str]) -> Dict[str, Any]:
        """Validate a group of related properties."""
        result = {
            "group": group_name,
            "passed": True,
            "properties": {},
            "issues": [],
        }

        for prop in properties:
            value = self._properties.get(prop, "")
            result["properties"][prop] = value

            # Check if property is set
            if not value:
                result["passed"] = False
                result["issues"].append(f"Property {prop} is not set")

            # Check for Cuttlefish/emulator artifacts
            if self._contains_emulator_artifacts(value):
                result["passed"] = False
                result["issues"].append(f"Property {prop} contains emulator artifacts: {value}")

        return result

    def _contains_emulator_artifacts(self, value: str) -> bool:
        """Check if property value contains emulator/Cuttlefish artifacts."""
        artifacts = [
            "cuttlefish",
            "vsoc",
            "virtio",
            "goldfish",
            "ranchu",
            "emulator",
            "qemu",
            "vbox",
            "generic",
        ]

        value_lower = value.lower()
        return any(artifact in value_lower for artifact in artifacts)

    def _validate_dependencies(self) -> List[Dict[str, Any]]:
        """Validate property interdependencies."""
        results = []

        model = self._properties.get("ro.product.model", "")
        if not model:
            return results

        # Check if model has defined dependencies
        for model_pattern, deps in self.PROPERTY_DEPENDENCIES.get("ro.product.model", {}).items():
            if model_pattern.lower() in model.lower():
                # Validate each dependency
                for dep_prop, expected_value in deps.items():
                    actual_value = self._properties.get(dep_prop, "")
                    passed = expected_value.lower() in actual_value.lower()

                    results.append({
                        "property": dep_prop,
                        "expected": expected_value,
                        "actual": actual_value,
                        "passed": passed,
                        "reason": f"Model {model} requires {dep_prop}={expected_value}",
                    })

        return results

    def _validate_against_real_profiles(self) -> Dict[str, Any]:
        """Validate properties against real device profiles."""
        warnings = []

        # Check build fingerprint format
        fingerprint = self._properties.get("ro.build.fingerprint", "")
        if fingerprint:
            # Format: brand/product/device:version/build_id/build_number:type/tags
            parts = fingerprint.split('/')
            if len(parts) < 3:
                warnings.append(f"Build fingerprint has invalid format: {fingerprint}")

        # Check SDK version consistency
        sdk = self._properties.get("ro.build.version.sdk", "")
        release = self._properties.get("ro.build.version.release", "")
        if sdk and release:
            # Validate SDK matches release version
            sdk_release_map = {
                "34": "14",
                "33": "13",
                "32": "12L",
                "31": "12",
                "30": "11",
            }
            expected_release = sdk_release_map.get(sdk, "")
            if expected_release and expected_release not in release:
                warnings.append(f"SDK {sdk} doesn't match release {release}")

        return {"warnings": warnings}

    def fix_inconsistencies(self, validation_result: PropertyValidationResult) -> bool:
        """Fix property inconsistencies."""
        from adb_utils import adb_shell as _adb_shell

        logger.info("Fixing property inconsistencies")

        for inconsistency in validation_result.inconsistencies:
            if "property" in inconsistency:
                # Fix single property
                prop = inconsistency["property"]
                expected = inconsistency.get("expected", "")
                if expected:
                    _adb_shell(self.target, f"setprop {prop} {expected}")
                    logger.info(f"Fixed {prop} = {expected}")

        return True

    def get_property_report(self) -> Dict[str, Any]:
        """Get detailed property report."""
        if not self._properties:
            self._load_properties()

        return {
            "total_properties": len(self._properties),
            "property_groups": {
                group: {prop: self._properties.get(prop, "") for prop in props}
                for group, props in self.PROPERTY_GROUPS.items()
            },
            "critical_properties": {
                prop: self._properties.get(prop, "")
                for group in self.PROPERTY_GROUPS.values()
                for prop in group
            },
        }
