#!/usr/bin/env python3
"""
Titan V13 — APK Analyzer
Extracts metadata and security characteristics from Android APK files.

Usage:
    python3 apk_analyzer.py <apk_path> [--output json|yaml|summary]
    python3 apk_analyzer.py banking/chase_mobile.apk --output json > chase_mobile.json
"""

import argparse
import json
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import hashlib
import sys
import os

# Add core to path for Titan imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

try:
    from apk_data_map import APK_DATA_MAP, get_app_map
except ImportError:
    APK_DATA_MAP = {}
    def get_app_map(package: str): return {}

class APKAnalyzer:
    """Analyzes APK files for metadata, permissions, and security characteristics."""

    def __init__(self, apk_path: str):
        self.apk_path = Path(apk_path)
        if not self.apk_path.exists():
            raise FileNotFoundError(f"APK file not found: {apk_path}")

        self.metadata = {}
        self._extract_basic_info()

    def _extract_basic_info(self):
        """Extract basic APK information using aapt."""
        try:
            # Try aapt2 first, fall back to aapt
            aapt_cmd = self._find_aapt_tool()
            if not aapt_cmd:
                raise RuntimeError("aapt/aapt2 not found in PATH")

            result = subprocess.run([
                aapt_cmd, 'dump', 'badging', str(self.apk_path)
            ], capture_output=True, text=True, check=True)

            self._parse_aapt_output(result.stdout)

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"Warning: Could not extract APK info with aapt: {e}", file=sys.stderr)
            # Fallback to manual ZIP parsing
            self._extract_manifest_manually()

    def _find_aapt_tool(self):
        """Find aapt or aapt2 in PATH."""
        for tool in ['aapt2', 'aapt']:
            if subprocess.run(['which', tool], capture_output=True).returncode == 0:
                return tool
        return None

    def _parse_aapt_output(self, output: str):
        """Parse aapt dump badging output."""
        for line in output.split('\n'):
            line = line.strip()

            if line.startswith('package:'):
                # package: name='com.chase.sig.android' versionCode='123' versionName='5.2.1'
                parts = line.split()
                for part in parts:
                    if part.startswith("name='"):
                        self.metadata['package_name'] = part.split("'")[1]
                    elif part.startswith("versionCode='"):
                        self.metadata['version_code'] = part.split("'")[1]
                    elif part.startswith("versionName='"):
                        self.metadata['version'] = part.split("'")[1]

            elif line.startswith('application-label:'):
                # application-label:'Chase Mobile'
                self.metadata['app_name'] = line.split("'")[1]

            elif line.startswith('uses-permission:'):
                # uses-permission: name='android.permission.CAMERA'
                if 'permissions' not in self.metadata:
                    self.metadata['permissions'] = []
                perm = line.split("'")[1]
                self.metadata['permissions'].append(perm)

    def _extract_manifest_manually(self):
        """Fallback: Extract AndroidManifest.xml manually from APK."""
        try:
            with zipfile.ZipFile(self.apk_path, 'r') as zf:
                # Basic info from file structure
                self.metadata['package_name'] = 'unknown'
                self.metadata['app_name'] = self.apk_path.stem
                self.metadata['version'] = 'unknown'
                self.metadata['permissions'] = []

                # Try to get file list for analysis
                files = zf.namelist()
                self.metadata['file_count'] = len(files)

                # Look for common detection libraries in lib/
                native_libs = [f for f in files if f.startswith('lib/') and f.endswith('.so')]
                self.metadata['native_libraries'] = native_libs

        except Exception as e:
            print(f"Warning: Manual extraction failed: {e}", file=sys.stderr)

    def analyze_security(self):
        """Analyze security characteristics and anti-emulation measures."""
        security = {
            'requires_root_hiding': False,
            'requires_play_integrity': 'BASIC',
            'detection_vectors': [],
            'antidetect_difficulty': 'LOW'
        }

        package = self.metadata.get('package_name', '')

        # Banking apps - high security
        if any(bank in package.lower() for bank in ['chase', 'bankofamerica', 'wells', 'citi', 'capitalone']):
            security.update({
                'requires_root_hiding': True,
                'requires_play_integrity': 'DEVICE',
                'detection_vectors': ['native_root_scan', 'magisk_process_check', 'proc_maps_scan'],
                'antidetect_difficulty': 'HIGH'
            })

        # Social media - medium security
        elif any(social in package.lower() for social in ['instagram', 'tiktok', 'snapchat', 'facebook']):
            security.update({
                'requires_root_hiding': True,
                'requires_play_integrity': 'BASIC',
                'detection_vectors': ['basic_root_check', 'emulator_props'],
                'antidetect_difficulty': 'MEDIUM'
            })

        # E-commerce - medium-high security
        elif any(shop in package.lower() for shop in ['amazon', 'ebay', 'walmart', 'target']):
            security.update({
                'requires_root_hiding': True,
                'requires_play_integrity': 'BASIC',
                'detection_vectors': ['device_fingerprint', 'play_integrity'],
                'antidetect_difficulty': 'MEDIUM'
            })

        # Check for common anti-emulation libraries
        libs = self.metadata.get('native_libraries', [])
        for lib in libs:
            if any(pattern in lib.lower() for pattern in ['arxan', 'promon', 'guardsquare', 'threatmetrix']):
                security['detection_vectors'].append('commercial_rasp')
                security['antidetect_difficulty'] = 'HIGH'

        self.metadata['security'] = security

    def calculate_trust_weight(self):
        """Calculate trust score contribution (0-10)."""
        package = self.metadata.get('package_name', '')

        # Banking apps: highest trust weight
        if any(bank in package.lower() for bank in ['chase', 'bankofamerica', 'wells', 'citi']):
            trust_weight = 9
        elif 'bank' in package.lower() or 'credit' in package.lower():
            trust_weight = 7

        # Social media: high trust weight
        elif any(social in package.lower() for social in ['instagram', 'tiktok', 'snapchat', 'facebook']):
            trust_weight = 7

        # E-commerce: high trust weight
        elif any(shop in package.lower() for shop in ['amazon', 'ebay', 'paypal', 'walmart']):
            trust_weight = 8

        # Communication: medium trust weight
        elif any(comm in package.lower() for comm in ['whatsapp', 'telegram', 'signal', 'discord']):
            trust_weight = 6

        # Productivity: medium trust weight
        elif any(prod in package.lower() for prod in ['microsoft', 'google', 'adobe', 'zoom']):
            trust_weight = 5

        # Games and entertainment: low-medium
        elif any(ent in package.lower() for ent in ['game', 'music', 'video', 'media']):
            trust_weight = 4

        # System and utilities: low
        else:
            trust_weight = 3

        self.metadata['trust_weight'] = trust_weight

    def categorize_app(self):
        """Determine app category based on package name and characteristics."""
        package = self.metadata.get('package_name', '').lower()
        app_name = self.metadata.get('app_name', '').lower()

        # Banking
        if any(term in package for term in ['bank', 'chase', 'wells', 'citi', 'capital']):
            category = 'banking'

        # Social
        elif any(term in package for term in ['instagram', 'tiktok', 'snap', 'facebook', 'twitter']):
            category = 'social'

        # E-commerce
        elif any(term in package for term in ['amazon', 'ebay', 'walmart', 'target', 'shop']):
            category = 'ecommerce'

        # Communication
        elif any(term in package for term in ['whatsapp', 'telegram', 'signal', 'discord', 'slack']):
            category = 'communication'

        # Finance/Investment
        elif any(term in package for term in ['robinhood', 'coinbase', 'crypto', 'trading', 'invest']):
            category = 'finance'

        # Entertainment
        elif any(term in package for term in ['game', 'music', 'video', 'netflix', 'spotify']):
            category = 'entertainment'

        # Productivity
        elif any(term in package for term in ['microsoft', 'office', 'adobe', 'zoom', 'slack']):
            category = 'productivity'

        # Utility
        elif any(term in package for term in ['launcher', 'keyboard', 'vpn', 'browser']):
            category = 'utility'

        # System
        elif any(term in package for term in ['android', 'google', 'system', 'samsung']):
            category = 'system'

        else:
            category = 'unknown'

        self.metadata['category'] = category

    def get_titan_integration_info(self):
        """Get Titan-specific integration information."""
        package = self.metadata.get('package_name', '')

        # Check if app is in APK_DATA_MAP
        app_map = get_app_map(package)
        if app_map:
            self.metadata['titan_integration'] = {
                'has_data_map': True,
                'shared_prefs': list(app_map.get('shared_prefs', {}).keys()),
                'databases': list(app_map.get('databases', {}).keys()),
                'auth_method': app_map.get('account_type', 'unknown'),
                'login_required': app_map.get('login_required', False),
                'has_payment': app_map.get('has_payment', False)
            }
        else:
            self.metadata['titan_integration'] = {
                'has_data_map': False,
                'needs_data_map': True
            }

    def calculate_file_hash(self):
        """Calculate APK file hash for integrity verification."""
        with open(self.apk_path, 'rb') as f:
            content = f.read()

        self.metadata['file_info'] = {
            'size_bytes': len(content),
            'size_mb': round(len(content) / 1024 / 1024, 2),
            'sha256': hashlib.sha256(content).hexdigest(),
            'md5': hashlib.md5(content).hexdigest()
        }

    def generate_full_analysis(self):
        """Generate complete APK analysis."""
        self.analyze_security()
        self.calculate_trust_weight()
        self.categorize_app()
        self.get_titan_integration_info()
        self.calculate_file_hash()

        # Add analysis metadata
        self.metadata['analyzed_at'] = subprocess.run(['date', '-Iseconds'],
                                                     capture_output=True, text=True).stdout.strip()
        self.metadata['analyzer_version'] = '13.0.0'

        return self.metadata

    def generate_summary(self):
        """Generate human-readable summary."""
        pkg = self.metadata.get('package_name', 'Unknown')
        name = self.metadata.get('app_name', 'Unknown')
        version = self.metadata.get('version', 'Unknown')
        category = self.metadata.get('category', 'unknown')
        trust_weight = self.metadata.get('trust_weight', 0)

        security = self.metadata.get('security', {})
        difficulty = security.get('antidetect_difficulty', 'UNKNOWN')
        play_integrity = security.get('requires_play_integrity', 'BASIC')

        summary = f"""
APK Analysis Summary
==================
App: {name} ({pkg})
Version: {version}
Category: {category}
Trust Weight: {trust_weight}/10

Security Profile:
- Antidetect Difficulty: {difficulty}
- Play Integrity Required: {play_integrity}
- Root Hiding Required: {security.get('requires_root_hiding', False)}
- Detection Vectors: {', '.join(security.get('detection_vectors', []))}

File Info:
- Size: {self.metadata.get('file_info', {}).get('size_mb', '?')} MB
- SHA256: {self.metadata.get('file_info', {}).get('sha256', '?')[:16]}...

Titan Integration:
- Has Data Map: {self.metadata.get('titan_integration', {}).get('has_data_map', False)}
- Auth Method: {self.metadata.get('titan_integration', {}).get('auth_method', 'unknown')}
"""
        return summary.strip()


def main():
    parser = argparse.ArgumentParser(description='Analyze Android APK files')
    parser.add_argument('apk_path', help='Path to APK file')
    parser.add_argument('--output', choices=['json', 'yaml', 'summary'],
                       default='summary', help='Output format')

    args = parser.parse_args()

    try:
        analyzer = APKAnalyzer(args.apk_path)

        if args.output == 'summary':
            result = analyzer.generate_full_analysis()
            print(analyzer.generate_summary())

        elif args.output == 'json':
            result = analyzer.generate_full_analysis()
            print(json.dumps(result, indent=2, sort_keys=True))

        elif args.output == 'yaml':
            result = analyzer.generate_full_analysis()
            try:
                import yaml
                print(yaml.dump(result, default_flow_style=False, sort_keys=True))
            except ImportError:
                print("PyYAML not installed, using JSON format:")
                print(json.dumps(result, indent=2, sort_keys=True))

    except Exception as e:
        print(f"Error analyzing APK: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
