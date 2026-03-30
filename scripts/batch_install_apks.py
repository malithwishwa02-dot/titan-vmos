#!/usr/bin/env python3
"""
Titan V13 — Batch APK Installer
Mass installation of APKs across VMOS Cloud/Edge instances with category-based profiles.

Usage:
    python3 batch_install_apks.py --profile banking_standard --devices ACP001,ACP002
    python3 batch_install_apks.py --category banking --devices all --dry-run
    python3 batch_install_apks.py --apk-list custom_list.json --devices ACP001
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Add core to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from vmos_cloud_api import VMOSCloudClient
from exponential_backoff import exponential_backoff

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BatchAPKInstaller:
    """Manages batch installation of APK files across VMOS devices."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.client = VMOSCloudClient()
        self.apk_base_path = Path(__file__).parent.parent / "apks"

        # Load installation profiles
        self.profiles = self._load_profiles()

    def _load_profiles(self) -> Dict:
        """Load predefined installation profiles."""
        return {
            "banking_standard": {
                "category": "banking",
                "apps": [
                    "chase_mobile.apk",
                    "bank_of_america.apk",
                    "wells_fargo.apk",
                    "capital_one.apk"
                ],
                "install_spacing": 300,  # 5 minutes between installs
                "auto_permissions": True,
                "post_install_actions": ["account_injection", "usage_simulation"]
            },

            "social_media_basic": {
                "category": "social",
                "apps": [
                    "instagram.apk",
                    "tiktok.apk",
                    "snapchat.apk",
                    "facebook.apk"
                ],
                "install_spacing": 600,  # 10 minutes between installs
                "auto_permissions": True,
                "post_install_actions": ["contact_injection", "usage_simulation"]
            },

            "ecommerce_shopper": {
                "category": "ecommerce",
                "apps": [
                    "amazon_mobile.apk",
                    "ebay.apk",
                    "walmart.apk",
                    "target.apk"
                ],
                "install_spacing": 450,  # 7.5 minutes between installs
                "auto_permissions": True,
                "post_install_actions": ["payment_injection", "browsing_history"]
            },

            "complete_profile": {
                "categories": ["banking", "social", "ecommerce", "communication"],
                "max_apps_per_category": 3,
                "install_spacing": 900,  # 15 minutes between installs
                "auto_permissions": True,
                "post_install_actions": ["full_injection", "trust_optimization"]
            }
        }

    async def get_available_devices(self) -> List[str]:
        """Get list of available VMOS Cloud devices."""
        try:
            result = await self.client.instance_list(page=1, rows=50)
            if result['code'] != 200:
                raise Exception(f"Failed to get instances: {result['msg']}")

            devices = []
            for instance in result['data'].get('records', []):
                if instance.get('status') == 10:  # Running status
                    devices.append(instance['padCode'])

            return devices

        except Exception as e:
            logger.error(f"Error getting device list: {e}")
            return []

    def get_apks_by_category(self, category: str) -> List[Path]:
        """Get all APK files in a specific category."""
        category_path = self.apk_base_path / category
        if not category_path.exists():
            logger.warning(f"Category directory not found: {category}")
            return []

        apks = list(category_path.glob("*.apk"))
        logger.info(f"Found {len(apks)} APKs in category '{category}'")
        return apks

    def get_apks_by_profile(self, profile_name: str) -> List[Path]:
        """Get APK files based on installation profile."""
        if profile_name not in self.profiles:
            raise ValueError(f"Unknown profile: {profile_name}")

        profile = self.profiles[profile_name]
        apks = []

        if "category" in profile:
            # Single category profile
            category_path = self.apk_base_path / profile["category"]
            for apk_name in profile["apps"]:
                apk_path = category_path / apk_name
                if apk_path.exists():
                    apks.append(apk_path)
                else:
                    logger.warning(f"APK not found: {apk_path}")

        elif "categories" in profile:
            # Multi-category profile
            max_per_cat = profile.get("max_apps_per_category", 5)
            for category in profile["categories"]:
                category_apks = self.get_apks_by_category(category)[:max_per_cat]
                apks.extend(category_apks)

        return apks

    @exponential_backoff(max_retries=3)
    async def install_single_apk(self, devices: List[str], apk_path: Path, auto_permissions: bool = True) -> Dict:
        """Install a single APK on specified devices."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would install {apk_path.name} on {len(devices)} devices")
            return {"success": True, "dry_run": True}

        try:
            # Convert to file:// URL for VMOS Cloud API
            apk_url = f"file://{apk_path.absolute()}"

            result = await self.client.install_app(
                pad_codes=devices,
                url=apk_url,
                is_authorization=auto_permissions
            )

            if result['code'] != 200:
                raise Exception(f"Installation failed: {result['msg']}")

            # Track async task for completion
            task_id = result['data'].get('taskId')
            if task_id:
                await self._wait_for_task_completion(task_id)

            logger.info(f"Successfully installed {apk_path.name} on {len(devices)} devices")
            return {"success": True, "task_id": task_id}

        except Exception as e:
            logger.error(f"Failed to install {apk_path.name}: {e}")
            return {"success": False, "error": str(e)}

    async def _wait_for_task_completion(self, task_id: str, timeout: int = 300) -> bool:
        """Wait for VMOS async task to complete."""
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                result = await self.client.task_details(task_id)
                if result['code'] == 200:
                    status = result['data'].get('status', 1)
                    if status == 3:  # Completed
                        return True
                    elif status in [-1, -2, -3, -4, -5]:  # Failed states
                        logger.error(f"Task {task_id} failed with status {status}")
                        return False

                await asyncio.sleep(5)  # Check every 5 seconds

            except Exception as e:
                logger.warning(f"Error checking task status: {e}")
                await asyncio.sleep(10)

        logger.warning(f"Task {task_id} timed out after {timeout} seconds")
        return False

    async def install_profile(self, profile_name: str, devices: List[str]) -> Dict:
        """Install APKs based on a predefined profile."""
        if profile_name not in self.profiles:
            raise ValueError(f"Unknown profile: {profile_name}")

        profile = self.profiles[profile_name]
        apks = self.get_apks_by_profile(profile_name)

        if not apks:
            logger.error(f"No APKs found for profile: {profile_name}")
            return {"success": False, "error": "No APKs found"}

        logger.info(f"Installing profile '{profile_name}' with {len(apks)} APKs on {len(devices)} devices")

        results = []
        install_spacing = profile.get("install_spacing", 300)
        auto_permissions = profile.get("auto_permissions", True)

        for i, apk_path in enumerate(apks):
            logger.info(f"Installing APK {i+1}/{len(apks)}: {apk_path.name}")

            result = await self.install_single_apk(devices, apk_path, auto_permissions)
            results.append({
                "apk": apk_path.name,
                "result": result
            })

            # Wait between installations (except for last one)
            if i < len(apks) - 1 and install_spacing > 0:
                logger.info(f"Waiting {install_spacing} seconds before next installation...")
                if not self.dry_run:
                    await asyncio.sleep(install_spacing)

        # Execute post-install actions
        post_actions = profile.get("post_install_actions", [])
        if post_actions and not self.dry_run:
            await self._execute_post_install_actions(devices, post_actions)

        return {
            "success": True,
            "profile": profile_name,
            "installed_apks": len([r for r in results if r["result"]["success"]]),
            "failed_apks": len([r for r in results if not r["result"]["success"]]),
            "results": results
        }

    async def _execute_post_install_actions(self, devices: List[str], actions: List[str]):
        """Execute post-installation actions like data injection."""
        logger.info(f"Executing post-install actions: {', '.join(actions)}")

        for action in actions:
            if action == "account_injection":
                # Inject Google accounts and app-specific accounts
                logger.info("Injecting account data...")
                # TODO: Integrate with profile_injector

            elif action == "usage_simulation":
                # Simulate app usage patterns
                logger.info("Simulating usage patterns...")
                # TODO: Integrate with app_data_forger

            elif action == "contact_injection":
                # Inject realistic contact lists
                logger.info("Injecting contact data...")
                # TODO: Integrate with android_profile_forge

            elif action == "payment_injection":
                # Inject payment methods and transaction history
                logger.info("Injecting payment data...")
                # TODO: Integrate with wallet_provisioner

            elif action == "trust_optimization":
                # Run trust score optimization
                logger.info("Running trust score optimization...")
                # TODO: Integrate with trust_scorer

    async def install_from_list(self, apk_list: List[str], devices: List[str]) -> Dict:
        """Install APKs from a custom list."""
        results = []

        for apk_name in apk_list:
            # Try to find APK in any category
            apk_path = None
            for category_dir in self.apk_base_path.iterdir():
                if category_dir.is_dir():
                    candidate = category_dir / apk_name
                    if candidate.exists():
                        apk_path = candidate
                        break

            if not apk_path:
                logger.error(f"APK not found: {apk_name}")
                results.append({"apk": apk_name, "result": {"success": False, "error": "Not found"}})
                continue

            result = await self.install_single_apk(devices, apk_path)
            results.append({"apk": apk_name, "result": result})

        return {
            "success": True,
            "installed_apks": len([r for r in results if r["result"]["success"]]),
            "failed_apks": len([r for r in results if not r["result"]["success"]]),
            "results": results
        }

    def generate_report(self, results: Dict) -> str:
        """Generate installation report."""
        report = []
        report.append("=" * 60)
        report.append("TITAN V13 - BATCH APK INSTALLATION REPORT")
        report.append("=" * 60)

        if "profile" in results:
            report.append(f"Profile: {results['profile']}")

        report.append(f"Total APKs: {results.get('installed_apks', 0) + results.get('failed_apks', 0)}")
        report.append(f"Successful: {results.get('installed_apks', 0)}")
        report.append(f"Failed: {results.get('failed_apks', 0)}")
        report.append("")

        if "results" in results:
            report.append("INDIVIDUAL RESULTS:")
            report.append("-" * 40)
            for item in results["results"]:
                status = "✅ SUCCESS" if item["result"]["success"] else "❌ FAILED"
                report.append(f"{item['apk']:<30} {status}")
                if not item["result"]["success"] and "error" in item["result"]:
                    report.append(f"  └─ Error: {item['result']['error']}")

        report.append("")
        report.append("=" * 60)

        return "\n".join(report)


async def main():
    parser = argparse.ArgumentParser(description='Batch install APKs on VMOS devices')
    parser.add_argument('--profile', help='Installation profile name')
    parser.add_argument('--category', help='APK category (banking, social, etc.)')
    parser.add_argument('--apk-list', help='JSON file with custom APK list')
    parser.add_argument('--devices', required=True,
                       help='Device list (comma-separated pad codes or "all")')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be installed without doing it')
    parser.add_argument('--output', help='Save report to file')

    args = parser.parse_args()

    # Initialize installer
    installer = BatchAPKInstaller(dry_run=args.dry_run)

    # Get device list
    if args.devices.lower() == 'all':
        devices = await installer.get_available_devices()
        if not devices:
            logger.error("No running devices found")
            return 1
    else:
        devices = [d.strip() for d in args.devices.split(',')]

    logger.info(f"Target devices: {devices}")

    try:
        # Determine installation mode
        if args.profile:
            results = await installer.install_profile(args.profile, devices)

        elif args.category:
            apks = installer.get_apks_by_category(args.category)
            apk_names = [apk.name for apk in apks]
            results = await installer.install_from_list(apk_names, devices)

        elif args.apk_list:
            with open(args.apk_list) as f:
                apk_data = json.load(f)
                if isinstance(apk_data, list):
                    apk_names = apk_data
                else:
                    apk_names = apk_data.get('apks', [])

            results = await installer.install_from_list(apk_names, devices)

        else:
            parser.error("Must specify --profile, --category, or --apk-list")

        # Generate and display report
        report = installer.generate_report(results)
        print(report)

        # Save report if requested
        if args.output:
            with open(args.output, 'w') as f:
                f.write(report)
            logger.info(f"Report saved to: {args.output}")

        return 0 if results["success"] else 1

    except Exception as e:
        logger.error(f"Installation failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
