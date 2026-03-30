#!/usr/bin/env python3
"""
Titan V13 — APK Trust Weight Calculator
Analyzes installed app portfolio and calculates trust optimization strategies.

Usage:
    python3 calculate_trust_weights.py --device ACP2509244LGV1MV
    python3 calculate_trust_weights.py --category banking --show-recommendations
    python3 calculate_trust_weights.py --profile complete_analysis --export json
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Add core to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from vmos_cloud_api import VMOSCloudClient
from trust_scorer import TrustScorer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TrustWeightCalculator:
    """Analyzes app portfolios and provides trust optimization recommendations."""

    # Trust weight database for popular apps
    APP_TRUST_WEIGHTS = {
        # Banking Apps (Trust Weight: 8-10)
        'com.chase.sig.android': {'weight': 9, 'category': 'banking', 'name': 'Chase Mobile'},
        'com.infonow.bofa': {'weight': 9, 'category': 'banking', 'name': 'Bank of America'},
        'com.wf.wellsfargomobile': {'weight': 8, 'category': 'banking', 'name': 'Wells Fargo'},
        'com.konylabs.capitalone': {'weight': 8, 'category': 'banking', 'name': 'Capital One'},
        'com.citi.citimobile': {'weight': 8, 'category': 'banking', 'name': 'Citi Mobile'},
        'com.usbank.mobilebanking': {'weight': 7, 'category': 'banking', 'name': 'US Bank'},

        # E-commerce Apps (Trust Weight: 7-9)
        'com.amazon.mShop.android.shopping': {'weight': 9, 'category': 'ecommerce', 'name': 'Amazon'},
        'com.ebay.mobile': {'weight': 8, 'category': 'ecommerce', 'name': 'eBay'},
        'com.paypal.android.p2pmobile': {'weight': 8, 'category': 'ecommerce', 'name': 'PayPal'},
        'com.walmart.android': {'weight': 7, 'category': 'ecommerce', 'name': 'Walmart'},
        'com.target.ui': {'weight': 7, 'category': 'ecommerce', 'name': 'Target'},

        # Social Media Apps (Trust Weight: 6-8)
        'com.instagram.android': {'weight': 8, 'category': 'social', 'name': 'Instagram'},
        'com.zhiliaoapp.musically': {'weight': 7, 'category': 'social', 'name': 'TikTok'},
        'com.snapchat.android': {'weight': 7, 'category': 'social', 'name': 'Snapchat'},
        'com.facebook.katana': {'weight': 7, 'category': 'social', 'name': 'Facebook'},
        'com.twitter.android': {'weight': 6, 'category': 'social', 'name': 'Twitter'},

        # Communication Apps (Trust Weight: 5-7)
        'com.whatsapp': {'weight': 7, 'category': 'communication', 'name': 'WhatsApp'},
        'org.telegram.messenger': {'weight': 6, 'category': 'communication', 'name': 'Telegram'},
        'org.thoughtcrime.securesms': {'weight': 6, 'category': 'communication', 'name': 'Signal'},
        'com.discord': {'weight': 5, 'category': 'communication', 'name': 'Discord'},

        # Finance/Investment Apps (Trust Weight: 6-8)
        'com.robinhood.android': {'weight': 8, 'category': 'finance', 'name': 'Robinhood'},
        'com.coinbase.android': {'weight': 7, 'category': 'finance', 'name': 'Coinbase'},
        'com.personalcapital.pcapandroid': {'weight': 6, 'category': 'finance', 'name': 'Personal Capital'},

        # Productivity Apps (Trust Weight: 4-6)
        'com.microsoft.office.outlook': {'weight': 6, 'category': 'productivity', 'name': 'Outlook'},
        'com.google.android.apps.docs': {'weight': 5, 'category': 'productivity', 'name': 'Google Docs'},
        'com.adobe.reader': {'weight': 4, 'category': 'productivity', 'name': 'Adobe Reader'},

        # Entertainment Apps (Trust Weight: 3-5)
        'com.netflix.mediaclient': {'weight': 5, 'category': 'entertainment', 'name': 'Netflix'},
        'com.spotify.music': {'weight': 5, 'category': 'entertainment', 'name': 'Spotify'},
        'com.google.android.youtube': {'weight': 4, 'category': 'entertainment', 'name': 'YouTube'},

        # System/Utility Apps (Trust Weight: 2-4)
        'com.teslacoilsw.launcher': {'weight': 4, 'category': 'utility', 'name': 'Nova Launcher'},
        'com.touchtype.swiftkey': {'weight': 3, 'category': 'utility', 'name': 'SwiftKey'},
        'com.android.chrome': {'weight': 3, 'category': 'utility', 'name': 'Chrome Browser'},
    }

    # Optimal trust weight distribution for maximum authenticity
    OPTIMAL_DISTRIBUTION = {
        'banking': {'target_weight': 25, 'min_apps': 2, 'max_apps': 4},
        'ecommerce': {'target_weight': 20, 'min_apps': 3, 'max_apps': 6},
        'social': {'target_weight': 15, 'min_apps': 3, 'max_apps': 5},
        'communication': {'target_weight': 10, 'min_apps': 2, 'max_apps': 4},
        'finance': {'target_weight': 8, 'min_apps': 1, 'max_apps': 3},
        'productivity': {'target_weight': 7, 'min_apps': 2, 'max_apps': 4},
        'entertainment': {'target_weight': 10, 'min_apps': 3, 'max_apps': 6},
        'utility': {'target_weight': 5, 'min_apps': 2, 'max_apps': 3}
    }

    def __init__(self):
        self.client = VMOSCloudClient()
        self.trust_scorer = TrustScorer()

    async def get_installed_apps(self, device_id: str) -> List[Dict]:
        """Get list of installed apps from VMOS device."""
        try:
            result = await self.client.list_installed_apps([device_id])
            if result['code'] != 200:
                raise Exception(f"Failed to get app list: {result['msg']}")

            apps = result['data'].get('apps', [])
            logger.info(f"Found {len(apps)} installed apps on device {device_id}")
            return apps

        except Exception as e:
            logger.error(f"Error getting app list: {e}")
            return []

    def calculate_app_trust_weight(self, package_name: str) -> Tuple[int, str, str]:
        """Calculate trust weight for a specific app package."""
        if package_name in self.APP_TRUST_WEIGHTS:
            app_info = self.APP_TRUST_WEIGHTS[package_name]
            return app_info['weight'], app_info['category'], app_info['name']

        # Heuristic weight calculation for unknown apps
        if any(keyword in package_name.lower() for keyword in ['bank', 'finance', 'pay']):
            return 7, 'finance', 'Unknown Banking App'
        elif any(keyword in package_name.lower() for keyword in ['shop', 'store', 'buy']):
            return 6, 'ecommerce', 'Unknown Shopping App'
        elif any(keyword in package_name.lower() for keyword in ['social', 'chat', 'message']):
            return 5, 'social', 'Unknown Social App'
        elif 'game' in package_name.lower():
            return 3, 'entertainment', 'Game App'
        else:
            return 2, 'utility', 'Unknown App'

    def analyze_app_portfolio(self, installed_apps: List[Dict]) -> Dict:
        """Analyze the trust weight distribution of installed apps."""
        analysis = {
            'total_apps': len(installed_apps),
            'total_trust_weight': 0,
            'category_breakdown': {},
            'high_value_apps': [],
            'low_value_apps': [],
            'missing_categories': [],
            'recommendations': []
        }

        # Initialize category counters
        for category in self.OPTIMAL_DISTRIBUTION:
            analysis['category_breakdown'][category] = {
                'apps': [],
                'count': 0,
                'total_weight': 0,
                'average_weight': 0
            }

        # Analyze each installed app
        for app in installed_apps:
            package_name = app.get('packageName', '')
            app_name = app.get('appName', package_name)

            weight, category, display_name = self.calculate_app_trust_weight(package_name)

            app_info = {
                'package_name': package_name,
                'app_name': app_name,
                'display_name': display_name,
                'trust_weight': weight,
                'category': category
            }

            analysis['total_trust_weight'] += weight
            analysis['category_breakdown'][category]['apps'].append(app_info)
            analysis['category_breakdown'][category]['count'] += 1
            analysis['category_breakdown'][category]['total_weight'] += weight

            # Classify apps by value
            if weight >= 7:
                analysis['high_value_apps'].append(app_info)
            elif weight <= 3:
                analysis['low_value_apps'].append(app_info)

        # Calculate category averages
        for category, data in analysis['category_breakdown'].items():
            if data['count'] > 0:
                data['average_weight'] = data['total_weight'] / data['count']

        # Identify missing critical categories
        for category, optimal in self.OPTIMAL_DISTRIBUTION.items():
            current_count = analysis['category_breakdown'][category]['count']
            if current_count < optimal['min_apps']:
                analysis['missing_categories'].append({
                    'category': category,
                    'current_apps': current_count,
                    'min_required': optimal['min_apps'],
                    'priority': 'HIGH' if category == 'banking' else 'MEDIUM'
                })

        return analysis

    def generate_recommendations(self, analysis: Dict) -> List[Dict]:
        """Generate specific recommendations for trust score optimization."""
        recommendations = []

        # Banking app recommendations (highest priority)
        banking_data = analysis['category_breakdown']['banking']
        if banking_data['count'] < 2:
            recommendations.append({
                'type': 'CRITICAL_MISSING',
                'category': 'banking',
                'priority': 'HIGH',
                'title': 'Install Banking Apps',
                'description': f'Only {banking_data["count"]} banking apps installed. Target: 2-4 apps.',
                'suggested_apps': ['Chase Mobile', 'Bank of America', 'Wells Fargo'],
                'expected_trust_gain': '+18-25 points'
            })

        # E-commerce recommendations
        ecommerce_data = analysis['category_breakdown']['ecommerce']
        if ecommerce_data['count'] < 3:
            recommendations.append({
                'type': 'IMPORTANT_MISSING',
                'category': 'ecommerce',
                'priority': 'MEDIUM',
                'title': 'Add E-commerce Apps',
                'description': f'Only {ecommerce_data["count"]} shopping apps. Target: 3-6 apps.',
                'suggested_apps': ['Amazon', 'eBay', 'PayPal', 'Walmart'],
                'expected_trust_gain': '+12-18 points'
            })

        # Social media balance
        social_data = analysis['category_breakdown']['social']
        if social_data['count'] == 0:
            recommendations.append({
                'type': 'DEMOGRAPHIC_GAP',
                'category': 'social',
                'priority': 'MEDIUM',
                'title': 'Add Social Media Apps',
                'description': 'No social media presence may appear suspicious.',
                'suggested_apps': ['Instagram', 'TikTok', 'Facebook'],
                'expected_trust_gain': '+10-15 points'
            })

        # Communication apps
        comm_data = analysis['category_breakdown']['communication']
        if comm_data['count'] < 2:
            recommendations.append({
                'type': 'COMMUNICATION_GAP',
                'category': 'communication',
                'priority': 'LOW',
                'title': 'Install Communication Apps',
                'description': 'Limited communication apps may reduce social authenticity.',
                'suggested_apps': ['WhatsApp', 'Telegram', 'Signal'],
                'expected_trust_gain': '+5-8 points'
            })

        # Over-optimization warning
        total_apps = analysis['total_apps']
        if total_apps > 50:
            recommendations.append({
                'type': 'WARNING',
                'category': 'general',
                'priority': 'MEDIUM',
                'title': 'Too Many Apps Installed',
                'description': f'{total_apps} apps may appear suspicious. Consider removing low-value apps.',
                'suggested_action': 'Remove utility and game apps',
                'expected_impact': 'Reduces detection risk'
            })

        # Trust weight optimization
        if analysis['total_trust_weight'] < 60:
            recommendations.append({
                'type': 'OPTIMIZATION',
                'category': 'general',
                'priority': 'HIGH',
                'title': 'Low Overall Trust Score',
                'description': f'Total trust weight: {analysis["total_trust_weight"]}. Target: 80-100.',
                'suggested_action': 'Focus on high-weight banking and e-commerce apps',
                'expected_trust_gain': '+20-40 points'
            })

        return recommendations

    def calculate_optimal_additions(self, analysis: Dict, target_score: int = 85) -> List[Dict]:
        """Calculate optimal app additions to reach target trust score."""
        current_score = analysis['total_trust_weight']
        needed_score = target_score - current_score

        if needed_score <= 0:
            return []

        suggestions = []

        # Priority order: Banking > E-commerce > Social > Finance > Communication
        priority_apps = [
            ('com.chase.sig.android', 'Chase Mobile', 9, 'banking'),
            ('com.infonow.bofa', 'Bank of America', 9, 'banking'),
            ('com.amazon.mShop.android.shopping', 'Amazon', 9, 'ecommerce'),
            ('com.wf.wellsfargomobile', 'Wells Fargo', 8, 'banking'),
            ('com.ebay.mobile', 'eBay', 8, 'ecommerce'),
            ('com.paypal.android.p2pmobile', 'PayPal', 8, 'ecommerce'),
            ('com.instagram.android', 'Instagram', 8, 'social'),
            ('com.robinhood.android', 'Robinhood', 8, 'finance'),
        ]

        # Check which apps are already installed
        installed_packages = set()
        for category_data in analysis['category_breakdown'].values():
            for app in category_data['apps']:
                installed_packages.add(app['package_name'])

        accumulated_gain = 0
        for package, name, weight, category in priority_apps:
            if package not in installed_packages and accumulated_gain < needed_score:
                suggestions.append({
                    'package_name': package,
                    'app_name': name,
                    'trust_weight': weight,
                    'category': category,
                    'cumulative_gain': accumulated_gain + weight
                })
                accumulated_gain += weight

                if accumulated_gain >= needed_score:
                    break

        return suggestions

    def generate_report(self, device_id: str, analysis: Dict, recommendations: List[Dict]) -> str:
        """Generate comprehensive trust analysis report."""
        lines = []

        lines.append("=" * 80)
        lines.append("TITAN V13 - TRUST WEIGHT ANALYSIS REPORT")
        lines.append("=" * 80)
        lines.append(f"Device: {device_id}")
        lines.append(f"Analysis Date: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # Summary
        lines.append("SUMMARY")
        lines.append("-" * 40)
        lines.append(f"Total Apps Installed: {analysis['total_apps']}")
        lines.append(f"Total Trust Weight: {analysis['total_trust_weight']}")
        lines.append(f"High-Value Apps (≥7): {len(analysis['high_value_apps'])}")
        lines.append(f"Low-Value Apps (≤3): {len(analysis['low_value_apps'])}")
        lines.append("")

        # Trust grade
        trust_weight = analysis['total_trust_weight']
        if trust_weight >= 90:
            grade = "A+ (Excellent)"
        elif trust_weight >= 75:
            grade = "A (Good)"
        elif trust_weight >= 60:
            grade = "B (Fair)"
        elif trust_weight >= 40:
            grade = "C (Poor)"
        else:
            grade = "F (Very Poor)"

        lines.append(f"Trust Grade: {grade}")
        lines.append("")

        # Category breakdown
        lines.append("CATEGORY BREAKDOWN")
        lines.append("-" * 40)
        for category, data in analysis['category_breakdown'].items():
            if data['count'] > 0:
                optimal = self.OPTIMAL_DISTRIBUTION[category]
                status = "✅" if data['count'] >= optimal['min_apps'] else "⚠️"
                lines.append(f"{status} {category.upper():<15} Apps: {data['count']:<2} Weight: {data['total_weight']:<3} "
                           f"Avg: {data['average_weight']:.1f}")
        lines.append("")

        # High-value apps
        if analysis['high_value_apps']:
            lines.append("HIGH-VALUE APPS (Trust Weight ≥7)")
            lines.append("-" * 40)
            for app in sorted(analysis['high_value_apps'], key=lambda x: x['trust_weight'], reverse=True):
                lines.append(f"• {app['display_name']:<30} Weight: {app['trust_weight']} ({app['category']})")
            lines.append("")

        # Recommendations
        if recommendations:
            lines.append("RECOMMENDATIONS")
            lines.append("-" * 40)
            for i, rec in enumerate(recommendations, 1):
                priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(rec['priority'], "📝")
                lines.append(f"{i}. {priority_icon} {rec['title']}")
                lines.append(f"   Priority: {rec['priority']}")
                lines.append(f"   {rec['description']}")
                if 'suggested_apps' in rec:
                    lines.append(f"   Suggested: {', '.join(rec['suggested_apps'])}")
                if 'expected_trust_gain' in rec:
                    lines.append(f"   Expected Gain: {rec['expected_trust_gain']}")
                lines.append("")

        # Missing categories
        if analysis['missing_categories']:
            lines.append("MISSING CRITICAL CATEGORIES")
            lines.append("-" * 40)
            for missing in analysis['missing_categories']:
                priority_icon = "🔴" if missing['priority'] == 'HIGH' else "🟡"
                lines.append(f"{priority_icon} {missing['category'].upper()}: "
                           f"{missing['current_apps']}/{missing['min_required']} apps installed")
            lines.append("")

        lines.append("=" * 80)
        return "\n".join(lines)

    async def analyze_device(self, device_id: str) -> Dict:
        """Perform complete trust analysis for a device."""
        logger.info(f"Analyzing device: {device_id}")

        # Get installed apps
        installed_apps = await self.get_installed_apps(device_id)
        if not installed_apps:
            return {"error": "Could not retrieve app list"}

        # Analyze portfolio
        analysis = self.analyze_app_portfolio(installed_apps)

        # Generate recommendations
        recommendations = self.generate_recommendations(analysis)
        analysis['recommendations'] = recommendations

        # Calculate optimal additions
        optimal_additions = self.calculate_optimal_additions(analysis)
        analysis['optimal_additions'] = optimal_additions

        return analysis


async def main():
    parser = argparse.ArgumentParser(description='Calculate trust weights for app portfolios')
    parser.add_argument('--device', help='VMOS device ID to analyze')
    parser.add_argument('--category', help='Analyze specific category weights')
    parser.add_argument('--profile', choices=['basic', 'detailed', 'complete_analysis'],
                       default='basic', help='Analysis profile')
    parser.add_argument('--show-recommendations', action='store_true',
                       help='Show optimization recommendations')
    parser.add_argument('--export', choices=['json', 'txt'], help='Export format')
    parser.add_argument('--output', help='Output file path')

    args = parser.parse_args()

    calculator = TrustWeightCalculator()

    try:
        if args.device:
            # Analyze specific device
            analysis = await calculator.analyze_device(args.device)

            if "error" in analysis:
                logger.error(f"Analysis failed: {analysis['error']}")
                return 1

            # Generate report
            report = calculator.generate_report(args.device, analysis, analysis['recommendations'])
            print(report)

            # Export if requested
            if args.export:
                output_path = args.output or f"trust_analysis_{args.device}.{args.export}"

                if args.export == 'json':
                    with open(output_path, 'w') as f:
                        json.dump(analysis, f, indent=2)
                else:
                    with open(output_path, 'w') as f:
                        f.write(report)

                logger.info(f"Report exported to: {output_path}")

        elif args.category:
            # Show category-specific analysis
            print(f"Trust Weight Analysis for Category: {args.category.upper()}")
            print("=" * 60)

            category_apps = {k: v for k, v in calculator.APP_TRUST_WEIGHTS.items()
                           if v['category'] == args.category}

            if not category_apps:
                print(f"No apps found for category: {args.category}")
                return 1

            total_weight = sum(app['weight'] for app in category_apps.values())
            print(f"Total Apps: {len(category_apps)}")
            print(f"Total Weight: {total_weight}")
            print(f"Average Weight: {total_weight / len(category_apps):.1f}")
            print()

            print("APPS IN CATEGORY:")
            for package, info in sorted(category_apps.items(), key=lambda x: x[1]['weight'], reverse=True):
                print(f"• {info['name']:<30} Weight: {info['weight']}")

        else:
            parser.error("Must specify --device or --category")

        return 0

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
