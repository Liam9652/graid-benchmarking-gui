#!/usr/bin/env python3
"""
Graid System Analysis Tool

This script analyzes various logs and configuration files to assess the health 
and configuration of a Graid storage system and related components.

Usage:
    python3 graid_analysis_script.py [--log-dir LOG_DIRECTORY] [--output OUTPUT_FILE] [--html] [--color] [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}]

Example:
    python3 graid_analysis_script.py --log-dir /path/to/logs --output report.txt --html --color --log-level INFO
"""

import os
import re
import datetime
import sys
import argparse
import json
import gzip
import logging
from pathlib import Path
from collections import defaultdict

# ANSI color codes for terminal output


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    # Severity colors
    CRITICAL = RED + BOLD
    HIGH = RED
    MEDIUM = YELLOW
    LOW = BLUE
    OK = GREEN


# Whether to use colors in output
USE_COLORS = False

# Collection of all issues found during analysis
ALL_ISSUES = []

# Parse command-line arguments


def parse_args():
    parser = argparse.ArgumentParser(description='Graid System Analysis Tool')
    parser.add_argument('--log-dir', type=str, default='.',
                        help='Directory containing the log files (default: current directory)')
    parser.add_argument('--output', type=str, default='graid_analysis_report.txt',
                        help='Output file for the analysis report (default: graid_analysis_report.txt)')
    parser.add_argument('--html', action='store_true',
                        help='Generate an HTML report in addition to text report')
    parser.add_argument('--color', action='store_true',
                        help='Use color in terminal output (text report will still be plain text)')
    parser.add_argument('--log-level', type=str, choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO', help='Set the logging level (default: INFO)')
    return parser.parse_args()


args = parse_args()

# Set color usage based on command line argument
USE_COLORS = args.color

# Define base paths based on command-line arguments
BASE_DIR = Path(args.log_dir)
REPORT_FILE = Path(args.output)

# Set up logging


def setup_logging(log_level):
    """Configure logging with appropriate level and format"""
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {log_level}')

    # Configure the root logger
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger('graid_analysis')


# Initialize logger
logger = setup_logging(args.log_level)


def add_issue(component, description, severity="MEDIUM", raw_data=None):
    """
    Add an issue to the global issues list

    :param component: Component with the issue (e.g., "Graid", "NVMe", "NVIDIA")
    :param description: Description of the issue
    :param severity: Severity level ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    :param raw_data: Raw data related to the issue
    """
    issue = {
        "component": component,
        "description": description,
        "severity": severity,
        "timestamp": datetime.datetime.now().isoformat(),
    }

    if raw_data:
        issue["raw_data"] = raw_data

    ALL_ISSUES.append(issue)
    return issue


def colorize(text, color_code):
    """Apply color to text if colors are enabled"""
    if USE_COLORS:
        return f"{color_code}{text}{Colors.RESET}"
    return text


def generate_executive_summary():
    """
    Generate an executive summary of all issues found during analysis
    """
    summary = []

    # Group issues by severity
    issues_by_severity = defaultdict(list)
    for issue in ALL_ISSUES:
        issues_by_severity[issue["severity"]].append(issue)

    # Add summary header
    summary.append(colorize("EXECUTIVE SUMMARY", Colors.BOLD))
    summary.append(colorize("="*80, Colors.BOLD))

    # Add issue counts
    total_issues = len(ALL_ISSUES)
    if total_issues == 0:
        summary.append(colorize(
            "No issues found. The system appears to be in good health.", Colors.GREEN))
        return "\n".join(summary)

    summary.append(
        f"Total issues found: {colorize(str(total_issues), Colors.BOLD)}")

    # Add counts by severity
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        count = len(issues_by_severity[severity])
        if count > 0:
            color = getattr(Colors, severity)
            summary.append(f"{colorize(severity, color)} issues: {count}")

    # List all critical issues
    if issues_by_severity["CRITICAL"]:
        summary.append(
            "\n" + colorize("CRITICAL ISSUES REQUIRING IMMEDIATE ATTENTION:", Colors.CRITICAL))
        for issue in issues_by_severity["CRITICAL"]:
            summary.append(f"- {issue['component']}: {issue['description']}")

    # List high severity issues
    if issues_by_severity["HIGH"]:
        summary.append("\n" + colorize("HIGH SEVERITY ISSUES:", Colors.HIGH))
        for issue in issues_by_severity["HIGH"]:
            summary.append(f"- {issue['component']}: {issue['description']}")

    # Summarize medium and low severity issues
    if issues_by_severity["MEDIUM"]:
        summary.append(
            f"\n{colorize('MEDIUM SEVERITY ISSUES:', Colors.MEDIUM)} {len(issues_by_severity['MEDIUM'])} found")

    if issues_by_severity["LOW"]:
        summary.append(
            f"{colorize('LOW SEVERITY ISSUES:', Colors.LOW)} {len(issues_by_severity['LOW'])} found")

    return "\n".join(summary)


def generate_html_report(all_results):
    """
    Generate an HTML version of the report

    :param all_results: List of all results from the analysis
    :return: HTML content as a string
    """
    html_output = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Graid System Analysis Report - {datetime.datetime.now().strftime('%Y-%m-%d')}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1, h2, h3, h4 {{
            color: #0066cc;
        }}
        h1 {{
            border-bottom: 2px solid #0066cc;
            padding-bottom: 10px;
        }}
        .section {{
            margin-bottom: 30px;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 15px;
            background-color: #f9f9f9;
        }}
        .section-title {{
            background-color: #0066cc;
            color: white;
            padding: 10px;
            margin: -15px -15px 15px -15px;
            border-radius: 5px 5px 0 0;
        }}
        .executive-summary {{
            background-color: #f0f7ff;
            border-left: 5px solid #0066cc;
        }}
        .issue {{
            margin-bottom: 10px;
            padding: 10px;
            border-radius: 5px;
        }}
        .critical {{
            background-color: #ffebee;
            border-left: 5px solid #d32f2f;
        }}
        .high {{
            background-color: #fff8e1;
            border-left: 5px solid #ff8f00;
        }}
        .medium {{
            background-color: #e8f5e9;
            border-left: 5px solid #388e3c;
        }}
        .low {{
            background-color: #e3f2fd;
            border-left: 5px solid #1976d2;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin-bottom: 15px;
        }}
        th, td {{
            text-align: left;
            padding: 12px;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #0066cc;
            color: white;
        }}
        tr:nth-child(even) {{
            background-color: #f2f2f2;
        }}
        .timestamp {{
            color: #666;
            font-size: 0.8em;
            text-align: right;
        }}
        pre {{
            background-color: #f5f5f5;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
        }}
    </style>
</head>
<body>
    <h1>Graid System Analysis Report</h1>
    <div class="timestamp">Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    
    <div class="section executive-summary">
        <h2 class="section-title">Executive Summary</h2>
        <div>
"""

    # Add executive summary
    total_issues = len(ALL_ISSUES)
    issues_by_severity = defaultdict(list)
    for issue in ALL_ISSUES:
        issues_by_severity[issue["severity"]].append(issue)

    if total_issues == 0:
        html_output += "<p><strong>No issues found. The system appears to be in good health.</strong></p>"
    else:
        html_output += f"<p><strong>Total issues found:</strong> {total_issues}</p>"
        html_output += "<ul>"
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = len(issues_by_severity[severity])
            if count > 0:
                html_output += f"<li><strong>{severity} issues:</strong> {count}</li>"
        html_output += "</ul>"

        # List critical issues
        if issues_by_severity["CRITICAL"]:
            html_output += "<h3>Critical Issues Requiring Immediate Attention:</h3>"
            html_output += "<div class='critical'>"
            for issue in issues_by_severity["CRITICAL"]:
                html_output += f"<p><strong>{issue['component']}:</strong> {issue['description']}</p>"
            html_output += "</div>"

        # List high severity issues
        if issues_by_severity["HIGH"]:
            html_output += "<h3>High Severity Issues:</h3>"
            html_output += "<div class='high'>"
            for issue in issues_by_severity["HIGH"]:
                html_output += f"<p><strong>{issue['component']}:</strong> {issue['description']}</p>"
            html_output += "</div>"

    html_output += """
        </div>
    </div>
    
    <div class="section">
        <h2 class="section-title">Detailed Analysis Results</h2>
"""

    # Add all analysis results
    current_section = None
    for line in all_results:
        if line.startswith("="):
            continue

        # Check if this is a section header
        if line.strip() and all(c == '=' for c in line):
            if current_section:
                html_output += "</div>\n"  # Close previous section
            html_output += f"<div class='section'>\n"
            current_section = True
            continue

        if current_section is None:
            html_output += f"<div class='section'>\n"
            current_section = True

        # Check if this is a section title (preceded by a number like "1. ")
        if re.match(r'^\d+\.\s+', line):
            html_output += f"<h3 class='section-title'>{line}</h3>\n"
            continue

        # Check for issue severity markers
        line_html = line
        if "✗" in line:
            line_html = f"<div class='issue high'>{line}</div>"
        elif "✓" in line:
            line_html = f"<div class='issue medium'>{line}</div>"

        html_output += f"<p>{line_html}</p>\n"

    if current_section:
        html_output += "</div>\n"  # Close last section

    # Add issues table
    if ALL_ISSUES:
        html_output += """
    <div class="section">
        <h2 class="section-title">All Issues</h2>
        <table>
            <tr>
                <th>Component</th>
                <th>Severity</th>
                <th>Description</th>
            </tr>
"""

        for issue in ALL_ISSUES:
            severity_class = issue["severity"].lower()
            html_output += f"""
            <tr class="{severity_class}">
                <td>{issue["component"]}</td>
                <td>{issue["severity"]}</td>
                <td>{issue["description"]}</td>
            </tr>
"""

        html_output += """
        </table>
    </div>
"""

    html_output += """
</body>
</html>
"""

    return html_output


def check_graid_logs():
    """
    Check Graid-related logs for issues:
    - Filter logs for warning/critical events in the last 3 days
    - Check for errors, failures, and configuration issues
    """
    results = []
    results.append(colorize("Checking Graid-related logs...", Colors.BOLD))

    # Get the timestamp from the last line of graid_server.log to determine three_days_ago
    graid_server_log = BASE_DIR / "graid_r" / "graid" / "graid_server.log"
    three_days_ago = None

    if graid_server_log.exists():
        try:
            # Read the last line of the file to get the latest timestamp
            last_line = ""
            with open(graid_server_log, 'r', errors='replace') as f:
                # Start from the end and read backwards until finding a non-empty line
                for line in reversed(list(f)):
                    if line.strip():
                        last_line = line.strip()
                        break

            # Parse the timestamp from the last line
            timestamp_match = re.search(r'\[([\d-]+ [\d:\.]+)\]', last_line)
            if timestamp_match:
                try:
                    # Parse timestamp without microseconds
                    timestamp_str = timestamp_match.group(1).split('.')[0]
                    log_date = datetime.datetime.strptime(
                        timestamp_str, "%Y-%m-%d %H:%M:%S")
                    three_days_ago = log_date - \
                        datetime.timedelta(days=7)  # Changed to 7 days
                    results.append(
                        f"Using reference timestamp from log: {log_date}")
                    results.append(
                        f"Checking for events after: {three_days_ago}")
                except ValueError:
                    results.append(
                        f"Failed to parse timestamp from log: {timestamp_match.group(1)}")
                    add_issue(
                        "Graid", "Failed to parse timestamp from log", "LOW")
        except Exception as e:
            results.append(
                f"Error reading last line from {graid_server_log}: {e}")
            add_issue(
                "Graid", f"Error reading graid_server.log: {e}", "MEDIUM")

    # If we couldn't determine three_days_ago from the log, use current time as fallback
    if three_days_ago is None:
        today = datetime.datetime.now()
        three_days_ago = today - \
            datetime.timedelta(days=7)  # Changed to 7 days
        results.append(f"Using current time as reference (fallback): {today}")
        results.append(f"Checking for events after: {three_days_ago}")

    # Helper function to parse dates from log lines with different formats
    def parse_date(line):
        date_formats = [
            "%Y-%m-%d %H:%M:%S",  # Standard format
            "%Y/%m/%d %H:%M:%S",  # Alternative format
            "%b %d %H:%M:%S %Y"   # Syslog format
        ]

        # Try to extract date from timestamp in brackets first
        timestamp_match = re.search(r'\[([\d-]+ [\d:\.]+)\]', line)
        if timestamp_match:
            timestamp_str = timestamp_match.group(1).split(
                '.')[0]  # Remove microseconds if present
            try:
                return datetime.datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass  # If this format fails, continue with other formats

        # Try standard formats
        for date_format in date_formats:
            try:
                # Try to extract date from beginning of line
                return datetime.datetime.strptime(line[:20].strip(), date_format)
            except ValueError:
                continue
        return None

    # 1. Check graid_server.log for warning or critical events
    graid_server_log = BASE_DIR / "graid_r" / "graid" / "graid_server.log"
    results.append(
        f"\n{colorize('Checking ' + str(graid_server_log) + ' for warning/critical events...', Colors.BOLD)}")

    if graid_server_log.exists():
        warning_critical_events = []
        try:
            with open(graid_server_log, 'r', errors='replace') as f:
                for line in f:
                    try:
                        # Parse date from log line
                        log_date = parse_date(line)
                        if log_date and log_date >= three_days_ago:
                            # Check for warning or critical level
                            lower_line = line.lower()
                            if "warning" in lower_line:
                                warning_critical_events.append(line.strip())
                                add_issue(
                                    "Graid", f"Warning event detected: {line.strip()}", "MEDIUM")
                            elif "critical" in lower_line:
                                warning_critical_events.append(line.strip())
                                add_issue(
                                    "Graid", f"Critical event detected: {line.strip()}", "HIGH")
                            elif "error" in lower_line:
                                warning_critical_events.append(line.strip())
                                add_issue(
                                    "Graid", f"Error event detected: {line.strip()}", "HIGH")
                    except Exception:
                        pass  # Skip problematic lines
        except Exception as e:
            results.append(f"Error reading {graid_server_log}: {e}")
            add_issue(
                "Graid", f"Error reading graid_server.log: {e}", "MEDIUM")

        if warning_critical_events:
            results.append(colorize(
                f"Found {len(warning_critical_events)} warning/critical/error events in last 7 days:", Colors.YELLOW))
            # Limit to 5 events in report
            for event in warning_critical_events[:5]:
                results.append(colorize(f"  - {event}", Colors.YELLOW))
            if len(warning_critical_events) > 5:
                results.append(
                    f"  ... and {len(warning_critical_events)-5} more events")
        else:
            results.append(
                colorize("No warning/critical/error events found in last 7 days", Colors.GREEN))
    else:
        results.append(f"Log file not found: {graid_server_log}")
        add_issue("Graid", f"Missing log file: {graid_server_log}", "MEDIUM")

    # 2. Check graid_core0.log and graid_core1.log for warning/critical events
    for core_log in ["graid_core0.log", "graid_core1.log"]:
        log_path = BASE_DIR / "graid_r" / "graid" / core_log
        results.append(
            f"\n{colorize('Checking ' + str(log_path) + ' for warning/critical events...', Colors.BOLD)}")

        if log_path.exists():
            warning_critical_events = []
            try:
                with open(log_path, 'r', errors='replace') as f:
                    for line in f:
                        try:
                            # Parse date from log line
                            log_date = parse_date(line)
                            if log_date and log_date >= three_days_ago:
                                # Check for warning or critical level
                                lower_line = line.lower()
                                if "warning" in lower_line:
                                    warning_critical_events.append(
                                        line.strip())
                                    add_issue(
                                        "Graid", f"Warning event detected in {core_log}: {line.strip()}", "MEDIUM")
                                elif "critical" in lower_line:
                                    warning_critical_events.append(
                                        line.strip())
                                    add_issue(
                                        "Graid", f"Critical event detected in {core_log}: {line.strip()}", "HIGH")
                                elif "error" in lower_line:
                                    warning_critical_events.append(
                                        line.strip())
                                    add_issue(
                                        "Graid", f"Error event detected in {core_log}: {line.strip()}", "HIGH")
                        except Exception:
                            pass  # Skip problematic lines
            except Exception as e:
                results.append(f"Error reading {log_path}: {e}")
                add_issue("Graid", f"Error reading {core_log}: {e}", "MEDIUM")

            if warning_critical_events:
                results.append(colorize(
                    f"Found {len(warning_critical_events)} warning/critical/error events in last 7 days:", Colors.YELLOW))
                # Limit to 5 events in report
                for event in warning_critical_events[:5]:
                    results.append(colorize(f"  - {event}", Colors.YELLOW))
                if len(warning_critical_events) > 5:
                    results.append(
                        f"  ... and {len(warning_critical_events)-5} more events")
            else:
                results.append(
                    colorize("No warning/critical/error events found in last 7 days", Colors.GREEN))
        else:
            results.append(f"Log file not found: {log_path}")
            add_issue("Graid", f"Missing log file: {log_path}", "LOW")

    # 3. Check upgrade_check.log for errors or fatal issues
    upgrade_check_log = BASE_DIR / "graid_r" / "graid" / "upgrade_check.log"
    results.append(
        f"\n{colorize('Checking ' + str(upgrade_check_log) + ' for errors or fatal issues...', Colors.BOLD)}")

    if upgrade_check_log.exists():
        errors_found = []
        try:
            with open(upgrade_check_log, 'r', errors='replace') as f:
                for line in f:
                    lower_line = line.lower()
                    if "error" in lower_line:
                        errors_found.append(line.strip())
                        add_issue(
                            "Graid", f"Error in upgrade check: {line.strip()}", "MEDIUM")
                    elif "fatal" in lower_line:
                        errors_found.append(line.strip())
                        add_issue(
                            "Graid", f"Fatal issue in upgrade check: {line.strip()}", "HIGH")
        except Exception as e:
            results.append(f"Error reading {upgrade_check_log}: {e}")
            add_issue(
                "Graid", f"Error reading upgrade_check.log: {e}", "MEDIUM")

        if errors_found:
            results.append(
                colorize(f"Found {len(errors_found)} error/fatal messages:", Colors.YELLOW))
            for error in errors_found[:5]:  # Limit to 5 errors in report
                results.append(colorize(f"  - {error}", Colors.YELLOW))
            if len(errors_found) > 5:
                results.append(
                    f"  ... and {len(errors_found)-5} more error messages")
        else:
            results.append(
                colorize("No error/fatal messages found", Colors.GREEN))
    else:
        results.append(f"Log file not found: {upgrade_check_log}")
        add_issue("Graid", f"Missing log file: {upgrade_check_log}", "LOW")

    # 4. Check preinstaller.log for failed messages
    preinstaller_log = BASE_DIR / "graid_r" / \
        "graid-preinstaller" / "preinstaller.log"
    results.append(
        f"\n{colorize('Checking ' + str(preinstaller_log) + ' for failed messages...', Colors.BOLD)}")

    if preinstaller_log.exists():
        failures_found = []
        try:
            with open(preinstaller_log, 'r', errors='replace') as f:
                for line in f:
                    if "failed" in line.lower():
                        failures_found.append(line.strip())
                        add_issue(
                            "Graid", f"Preinstaller failure: {line.strip()}", "HIGH")
        except Exception as e:
            results.append(f"Error reading {preinstaller_log}: {e}")
            add_issue(
                "Graid", f"Error reading preinstaller.log: {e}", "MEDIUM")

        if failures_found:
            results.append(
                colorize(f"Found {len(failures_found)} failure messages:", Colors.RED))
            for failure in failures_found[:5]:  # Limit to 5 failures in report
                results.append(colorize(f"  - {failure}", Colors.RED))
            if len(failures_found) > 5:
                results.append(
                    f"  ... and {len(failures_found)-5} more failure messages")
        else:
            results.append(colorize("No failure messages found", Colors.GREEN))
    else:
        results.append(f"Log file not found: {preinstaller_log}")
        add_issue("Graid", f"Missing log file: {preinstaller_log}", "LOW")

    # 5. Check error.tmp
    error_tmp = BASE_DIR / "graid_r" / "graid-preinstaller" / "error.tmp"
    results.append(
        f"\n{colorize('Checking ' + str(error_tmp) + '...', Colors.BOLD)}")

    if error_tmp.exists():
        try:
            with open(error_tmp, 'r', errors='replace') as f:
                content = f.read().strip()
                if content:
                    results.append(
                        colorize(f"Content of error.tmp:", Colors.RED))
                    if len(content) > 500:  # If content is too long, truncate it
                        results.append(
                            colorize(content[:500] + "... (truncated)", Colors.RED))
                    else:
                        results.append(colorize(content, Colors.RED))
                    add_issue(
                        "Graid", f"Error found in error.tmp: {content[:100]}...", "HIGH")
                else:
                    results.append(
                        colorize("error.tmp is empty", Colors.GREEN))
        except Exception as e:
            results.append(f"Error reading {error_tmp}: {e}")
            add_issue("Graid", f"Error reading error.tmp: {e}", "MEDIUM")
    else:
        results.append(f"File not found: {error_tmp}")

    # 6. Check installer.log for failed messages
    installer_log = BASE_DIR / "graid_r" / "graid-installer" / "installer.log"
    results.append(
        f"\n{colorize('Checking ' + str(installer_log) + ' for failed messages...', Colors.BOLD)}")

    if installer_log.exists():
        failures_found = []
        try:
            with open(installer_log, 'r', errors='replace') as f:
                for line in f:
                    if "failed" in line.lower():
                        failures_found.append(line.strip())
                        add_issue(
                            "Graid", f"Installer failure: {line.strip()}", "HIGH")
        except Exception as e:
            results.append(f"Error reading {installer_log}: {e}")
            add_issue("Graid", f"Error reading installer.log: {e}", "MEDIUM")

        if failures_found:
            results.append(
                colorize(f"Found {len(failures_found)} failure messages:", Colors.RED))
            for failure in failures_found[:5]:  # Limit to 5 failures in report
                results.append(colorize(f"  - {failure}", Colors.RED))
            if len(failures_found) > 5:
                results.append(
                    f"  ... and {len(failures_found)-5} more failure messages")
        else:
            results.append(colorize("No failure messages found", Colors.GREEN))
    else:
        results.append(f"Log file not found: {installer_log}")
        add_issue("Graid", f"Missing log file: {installer_log}", "LOW")

    # 7. Check graid_basic_info.log for license and service status
    basic_info_log = BASE_DIR / "graid_r" / "graid_basic_info.log"
    results.append(
        f"\n{colorize('Checking ' + str(basic_info_log) + ' for license and service status...', Colors.BOLD)}")

    if basic_info_log.exists():
        license_applied = False
        service_graid_running = False
        service_graid_mgr_running = False

        try:
            with open(basic_info_log, 'r', errors='replace') as f:
                content = f.read()
                # Check for license applied
                if re.search(r'license.*applied', content, re.IGNORECASE):
                    license_applied = True
                else:
                    add_issue("Graid", "Graid license not applied", "HIGH")

                # Check for graid service running with the correct pattern
                graid_service_match = re.search(
                    r'graid\.service.*\n.*\n.*Active: active', content, re.IGNORECASE)
                if graid_service_match:
                    service_graid_running = True
                else:
                    add_issue("Graid", "Graid service not running", "HIGH")

                # Check for graid-mgr service running with the correct pattern
                graid_mgr_service_match = re.search(
                    r'graid-mgr\.service.*\n.*\n.*Active: active \(running\)', content, re.IGNORECASE)
                if graid_mgr_service_match:
                    service_graid_mgr_running = True
                else:
                    add_issue(
                        "Graid", "Graid Manager service not running", "MEDIUM")
        except Exception as e:
            results.append(f"Error reading {basic_info_log}: {e}")
            add_issue("Graid", f"Error reading basic info log: {e}", "MEDIUM")

        results.append(
            f"License applied: {colorize('Yes', Colors.GREEN) if license_applied else colorize('No', Colors.RED)}")
        results.append(
            f"Graid service running: {colorize('Yes', Colors.GREEN) if service_graid_running else colorize('No', Colors.RED)}")
        results.append(
            f"Graid-MGR service running: {colorize('Yes', Colors.GREEN) if service_graid_mgr_running else colorize('No', Colors.RED)}")
    else:
        results.append(f"Log file not found: {basic_info_log}")
        add_issue("Graid", f"Missing log file: {basic_info_log}", "MEDIUM")

    # 8. Check check_cmdline.log for required parameters
    cmdline_log = BASE_DIR / "graid_r" / "check_cmdline.log"
    results.append(
        f"\n{colorize('Checking ' + str(cmdline_log) + ' for required parameters...', Colors.BOLD)}")

    if cmdline_log.exists():
        iommu_param = False
        nvme_param = False
        try:
            with open(cmdline_log, 'r', errors='replace') as f:
                content = f.read()
                iommu_param = "iommu=pt" in content
                nvme_param = "nvme_core.multipath=Y" in content

                if not iommu_param:
                    add_issue(
                        "System", "Missing kernel parameter: iommu=pt", "HIGH")

                if not nvme_param:
                    add_issue(
                        "System", "Missing kernel parameter: nvme_core.multipath=Y", "HIGH")
        except Exception as e:
            results.append(f"Error reading {cmdline_log}: {e}")
            add_issue(
                "System", f"Error reading check_cmdline.log: {e}", "MEDIUM")

        results.append(
            f"'iommu=pt' parameter found: {colorize('Yes', Colors.GREEN) if iommu_param else colorize('No', Colors.RED)}")
        results.append(
            f"'nvme_core.multipath=Y' parameter found: {colorize('Yes', Colors.GREEN) if nvme_param else colorize('No', Colors.RED)}")
    else:
        results.append(f"Log file not found: {cmdline_log}")
        add_issue("System", f"Missing log file: {cmdline_log}", "MEDIUM")

    return results


def check_nv_info():
    """
    Check NVIDIA information logs:
    - Link width compared to maximum
    - Link generation compared to "Device Max"
    - Active clocks event reasons (excluding idle)
    """
    results = []
    results.append(
        colorize("Checking NVIDIA information logs...", Colors.BOLD))

    nv_info_log = BASE_DIR / "basic_info" / "nv_info.log"
    results.append(
        f"\n{colorize('Checking ' + str(nv_info_log) + '...', Colors.BOLD)}")
    logger.info(f"Analyzing NVIDIA information log: {nv_info_log}")

    if nv_info_log.exists():
        try:
            with open(nv_info_log, 'r', errors='replace') as f:
                content = f.read()

                # 1. Check link width
                width_equal_max = "Unknown"
                width_pattern = re.compile(
                    r'Link Width\s*Max\s*:\s*(\d+)x\s*Current\s*:\s*(\d+)x', re.IGNORECASE | re.DOTALL)
                width_match = width_pattern.search(content)
                if width_match:
                    max_width = int(width_match.group(1))
                    current_width = int(width_match.group(2))
                    width_equal_max = current_width == max_width

                    results.append(
                        f"Link width: Current={current_width}x, Max={max_width}x, Equal={colorize('Yes', Colors.GREEN) if width_equal_max else colorize('No', Colors.RED)}")
                    logger.info(
                        f"GPU Link width: Current={current_width}x, Max={max_width}x, Equal={width_equal_max}")

                    if not width_equal_max:
                        add_issue(
                            "NVIDIA", f"GPU link width ({current_width}x) is less than maximum ({max_width}x)", "MEDIUM")
                        logger.warning(
                            f"GPU link width ({current_width}x) is less than maximum ({max_width}x)")
                else:
                    results.append(
                        colorize("Failed to find link width information", Colors.YELLOW))
                    add_issue(
                        "NVIDIA", "Could not determine GPU link width", "LOW")
                    logger.warning("Failed to find GPU link width information")

                # 2. Check PCIe Generation
                gen_equal_device_max = "Unknown"
                gen_pattern = re.compile(
                    r'PCIe Generation\s*Max\s*:\s*(\d+)\s*Current\s*:\s*(\d+)\s*Device Current\s*:\s*(\d+)\s*Device Max\s*:\s*(\d+)', re.IGNORECASE | re.DOTALL)
                gen_match = gen_pattern.search(content)
                if gen_match:
                    max_gen = gen_match.group(1)
                    current_gen = gen_match.group(2)
                    device_current_gen = gen_match.group(3)
                    device_max_gen = gen_match.group(4)

                    gen_equal_device_max = current_gen == device_max_gen
                    results.append(
                        f"PCIe Generation: Max={max_gen}, Current={current_gen}, Device Current={device_current_gen}, Device Max={device_max_gen}")
                    results.append(
                        f"Current generation equal to Device Max: {colorize('Yes', Colors.GREEN) if gen_equal_device_max else colorize('No', Colors.RED)}")
                    logger.info(
                        f"GPU PCIe Generation: Max={max_gen}, Current={current_gen}, Device Current={device_current_gen}, Device Max={device_max_gen}")

                    if not gen_equal_device_max:
                        add_issue(
                            "NVIDIA", f"GPU PCIe generation ({current_gen}) is less than device maximum ({device_max_gen})", "MEDIUM")
                        logger.warning(
                            f"GPU PCIe generation ({current_gen}) is less than device maximum ({device_max_gen})")
                else:
                    results.append(
                        colorize("Failed to find PCIe generation information", Colors.YELLOW))
                    add_issue(
                        "NVIDIA", "Could not determine GPU PCIe generation", "LOW")
                    logger.warning(
                        "Failed to find GPU PCIe generation information")

                # 3. Check clocks event reasons
                active_reasons = []
                clocks_section_patterns = [
                    # Pattern without colon after section title
                    r'Clocks Event Reasons\s*(.*?)(?=\n\s*\w+:|$)',
                    # Pattern with colon after section title
                    r'Clocks Event Reasons:(.*?)(?=\n\s*\w+:|$)'
                ]

                clocks_section = None
                for pattern in clocks_section_patterns:
                    match = re.search(pattern, content, re.DOTALL)
                    if match:
                        clocks_section = match
                        break

                if clocks_section:
                    reasons_text = clocks_section.group(1)

                    # Use a simpler, more direct approach to parse the entries
                    lines = reasons_text.strip().split('\n')
                    for line in lines:
                        line = line.strip()
                        if ':' in line:
                            reason, state = [part.strip()
                                             for part in line.split(':', 1)]

                            # Check if this is an actual event reason and not a header or empty line
                            if reason and state in ["Active", "Not Active"]:
                                if state == "Active" and reason.lower() != "idle":
                                    active_reasons.append(reason)
                                    logger.debug(
                                        f"Found active clock event reason: {reason}")

                    if active_reasons:
                        results.append(
                            colorize(f"Active clock event reasons (excluding idle):", Colors.YELLOW))
                        for reason in active_reasons:
                            results.append(
                                colorize(f"  - {reason}", Colors.YELLOW))
                            add_issue(
                                "NVIDIA", f"Active clock event reason: {reason}", "MEDIUM")
                        logger.warning(
                            f"Found {len(active_reasons)} active clock event reasons: {', '.join(active_reasons)}")
                    else:
                        results.append(
                            colorize("No active clock event reasons (excluding idle)", Colors.GREEN))
                        logger.info(
                            "No active clock event reasons (excluding idle)")
                else:
                    results.append(
                        colorize("Failed to find clocks event reasons section", Colors.YELLOW))
                    add_issue(
                        "NVIDIA", "Could not determine GPU clock event reasons", "LOW")
                    logger.warning(
                        "Failed to find GPU clocks event reasons section")
        except Exception as e:
            results.append(f"Error reading {nv_info_log}: {e}")
            add_issue(
                "NVIDIA", f"Error reading NVIDIA information log: {e}", "MEDIUM")
            logger.error(
                f"Error reading NVIDIA information log {nv_info_log}: {e}", exc_info=True)
    else:
        results.append(f"Log file not found: {nv_info_log}")
        add_issue("NVIDIA", f"Missing NVIDIA information log", "MEDIUM")
        logger.warning(f"NVIDIA information log not found: {nv_info_log}")

    return results


def check_nvme_logs():
    """
    Check NVMe logs:
    - Link speed compared to maximum
    - Link width compared to maximum
    - Support for Data Set Management
    - Support for Deallocated Logical Block feature
    """
    results = []
    results.append(colorize("Checking NVMe logs...", Colors.BOLD))

    nvme_log = BASE_DIR / "nvme" / "nvme.log"
    results.append(
        f"\n{colorize('Checking ' + str(nvme_log) + '...', Colors.BOLD)}")
    logger.info(f"Analyzing NVMe log: {nvme_log}")

    if nvme_log.exists():
        try:
            with open(nvme_log, 'r', errors='replace') as f:
                content = f.read()

                # Split the content into device sections
                device_sections = content.split("======================")
                device_count = 0

                # Stats counters
                link_speed_match_count = 0
                link_width_match_count = 0
                dsm_support_count = 0
                deallocated_zero_count = 0

                # Store device info for detailed reporting
                device_info = []

                # Process each device section
                for section in device_sections:
                    section = section.strip()
                    if not section:
                        continue

                    device_count += 1
                    device_data = {}

                    # Extract device name
                    device_name_match = re.search(
                        r'^([a-zA-Z0-9]+)_', section, re.MULTILINE)
                    if device_name_match:
                        device_name = device_name_match.group(1)
                        device_data['name'] = device_name
                    else:
                        device_name = f"device_{device_count}"
                        device_data['name'] = device_name

                    logger.debug(f"Analyzing NVMe device: {device_name}")

                    # Extract current and max link speed
                    current_speed_match = re.search(
                        r'([a-zA-Z0-9]+)_current_link_speed:\s*([^\n]+)', section)
                    max_speed_match = re.search(
                        r'([a-zA-Z0-9]+)_max_link_speed:\s*([^\n]+)', section)

                    if current_speed_match and max_speed_match:
                        current_speed = current_speed_match.group(2).strip()
                        max_speed = max_speed_match.group(2).strip()
                        device_data['current_speed'] = current_speed
                        device_data['max_speed'] = max_speed

                        # Check if current speed matches max speed
                        if current_speed == max_speed:
                            link_speed_match_count += 1
                            device_data['speed_match'] = True
                            logger.debug(
                                f"Device {device_name} link speed OK: {current_speed}")
                        else:
                            device_data['speed_match'] = False
                            add_issue(
                                "NVMe", f"Device {device_name} link speed ({current_speed}) is less than maximum ({max_speed})", "MEDIUM")
                            logger.warning(
                                f"Device {device_name} link speed ({current_speed}) is less than maximum ({max_speed})")

                    # Extract current and max link width
                    current_width_match = re.search(
                        r'([a-zA-Z0-9]+)_current_link_width:\s*(\d+)', section)
                    max_width_match = re.search(
                        r'([a-zA-Z0-9]+)_max_link_width:\s*(\d+)', section)

                    if current_width_match and max_width_match:
                        current_width = int(current_width_match.group(2))
                        max_width = int(max_width_match.group(2))
                        device_data['current_width'] = current_width
                        device_data['max_width'] = max_width

                        # Check if current width matches max width
                        if current_width == max_width:
                            link_width_match_count += 1
                            device_data['width_match'] = True
                            logger.debug(
                                f"Device {device_name} link width OK: {current_width}x")
                        else:
                            device_data['width_match'] = False
                            add_issue(
                                "NVMe", f"Device {device_name} link width ({current_width}x) is less than maximum ({max_width}x)", "MEDIUM")
                            logger.warning(
                                f"Device {device_name} link width ({current_width}x) is less than maximum ({max_width}x)")

                    # Check Data Set Management support
                    dsm_match = re.search(
                        r'([a-zA-Z0-9]+)_Data Set Management:.*?:\s*0x1\s*Data Set Management Supported', section)
                    if dsm_match:
                        dsm_support_count += 1
                        device_data['dsm_supported'] = True
                        logger.debug(
                            f"Device {device_name} supports Data Set Management")
                    else:
                        device_data['dsm_supported'] = False
                        add_issue(
                            "NVMe", f"Device {device_name} does not support Data Set Management", "LOW")
                        logger.info(
                            f"Device {device_name} does not support Data Set Management")

                    # Check Deallocated Logical Block feature
                    deallocated_match = re.search(
                        r'([a-zA-Z0-9]+)_Deallocated:.*?:\s*0x1\s*Bytes Read From a Deallocated Logical Block and its Metadata are 0x00', section)
                    if deallocated_match:
                        deallocated_zero_count += 1
                        device_data['deallocated_zero'] = True
                        logger.debug(
                            f"Device {device_name} supports Deallocated Logical Block with 0x00 metadata")
                    else:
                        device_data['deallocated_zero'] = False
                        add_issue(
                            "NVMe", f"Device {device_name} does not support Deallocated Logical Block with 0x00 metadata", "LOW")
                        logger.info(
                            f"Device {device_name} does not support Deallocated Logical Block with 0x00 metadata")

                    # Add device info to the list
                    device_info.append(device_data)

                # Report overall statistics
                if device_count > 0:
                    results.append(
                        f"Found {device_count} NVMe devices in the log")
                    results.append(
                        f"Link speed at maximum: {link_speed_match_count}/{device_count} devices")
                    results.append(
                        f"Link width at maximum: {link_width_match_count}/{device_count} devices")
                    results.append(
                        f"Data Set Management Supported: {dsm_support_count}/{device_count} devices")
                    results.append(
                        f"Deallocated Logical Block and its Metadata are 0x00: {deallocated_zero_count}/{device_count} devices")

                    logger.info(
                        f"Found {device_count} NVMe devices in the log")
                    logger.info(
                        f"Link speed at maximum: {link_speed_match_count}/{device_count} devices")
                    logger.info(
                        f"Link width at maximum: {link_width_match_count}/{device_count} devices")
                    logger.info(
                        f"Data Set Management Supported: {dsm_support_count}/{device_count} devices")
                    logger.info(
                        f"Deallocated Logical Block and Metadata=0x00: {deallocated_zero_count}/{device_count} devices")

                    # Detailed per-device report - only show devices with issues
                    devices_with_issues = [d for d in device_info if
                                           not d.get('speed_match', True) or
                                           not d.get('width_match', True) or
                                           not d.get('dsm_supported', True) or
                                           not d.get('deallocated_zero', True)]

                    if devices_with_issues:
                        results.append(
                            "\n" + colorize("NVMe Devices with Issues:", Colors.YELLOW))
                        logger.warning(
                            f"Found {len(devices_with_issues)} NVMe devices with issues")

                        for device in devices_with_issues:
                            results.append(
                                f"\n{colorize('Device: ' + device.get('name', 'Unknown'), Colors.BOLD)}")
                            logger.warning(
                                f"Issues for device: {device.get('name', 'Unknown')}")

                            # Only show details for checks that failed
                            if 'speed_match' in device and not device['speed_match']:
                                results.append(colorize(
                                    f"  ✗ Link Speed: Current={device['current_speed']}, Max={device['max_speed']}", Colors.YELLOW))
                                logger.warning(
                                    f"  Link Speed issue: Current={device['current_speed']}, Max={device['max_speed']}")

                            if 'width_match' in device and not device['width_match']:
                                results.append(colorize(
                                    f"  ✗ Link Width: Current={device['current_width']}x, Max={device['max_width']}x", Colors.YELLOW))
                                logger.warning(
                                    f"  Link Width issue: Current={device['current_width']}x, Max={device['max_width']}x")

                            if not device.get('dsm_supported', True):
                                results.append(
                                    colorize(f"  ✗ Data Set Management NOT Supported", Colors.YELLOW))
                                logger.info(
                                    f"  Data Set Management NOT Supported")

                            if not device.get('deallocated_zero', True):
                                results.append(
                                    colorize(f"  ✗ Deallocated Logical Block Metadata is NOT 0x00", Colors.YELLOW))
                                logger.info(
                                    f"  Deallocated Logical Block Metadata is NOT 0x00")
                    else:
                        results.append(
                            "\n" + colorize("✓ All NVMe devices have optimal configuration", Colors.GREEN))
                        logger.info(
                            "All NVMe devices have optimal configuration")
                else:
                    results.append(
                        colorize("No NVMe devices found in the log", Colors.YELLOW))
                    add_issue(
                        "NVMe", "No NVMe devices found in the log", "MEDIUM")
                    logger.warning("No NVMe devices found in the log")
        except Exception as e:
            results.append(f"Error reading {nvme_log}: {e}")
            add_issue("NVMe", f"Error reading NVMe log: {e}", "MEDIUM")
            logger.error(
                f"Error reading NVMe log {nvme_log}: {e}", exc_info=True)
    else:
        results.append(f"Log file not found: {nvme_log}")
        add_issue("NVMe", f"Missing NVMe log", "MEDIUM")
        logger.warning(f"NVMe log not found: {nvme_log}")

    return results


def check_dkms():
    """
    Check DKMS output:
    - Check for graid and nvidia packages
    - Verify there are no warning statuses
    """
    results = []
    results.append(colorize("Checking DKMS status...", Colors.BOLD))

    dkms_lib_dir = BASE_DIR / "logs" / "dkms_lib"
    results.append(
        f"\n{colorize('Checking DKMS in ' + str(dkms_lib_dir) + '...', Colors.BOLD)}")
    logger.info(f"Analyzing DKMS packages in: {dkms_lib_dir}")

    if dkms_lib_dir.exists():
        graid_dir = dkms_lib_dir / "graid"
        nvidia_dir = dkms_lib_dir / "nvidia"

        graid_installed = graid_dir.exists()
        nvidia_installed = nvidia_dir.exists()

        if not graid_installed:
            add_issue("System", "Graid DKMS package not installed", "HIGH")
            logger.error("Graid DKMS package not installed")

        if not nvidia_installed:
            add_issue("System", "NVIDIA DKMS package not installed", "HIGH")
            logger.error("NVIDIA DKMS package not installed")

        results.append(
            f"Graid package installed: {colorize('Yes', Colors.GREEN) if graid_installed else colorize('No', Colors.RED)}")
        results.append(
            f"NVIDIA package installed: {colorize('Yes', Colors.GREEN) if nvidia_installed else colorize('No', Colors.RED)}")

        logger.info(f"Graid DKMS package installed: {graid_installed}")
        logger.info(f"NVIDIA DKMS package installed: {nvidia_installed}")

        # Function to check warning statuses in installation logs
        def check_warnings(directory):
            warnings_found = False
            warning_messages = []

            for log_file in directory.glob("**/make.log"):
                try:
                    logger.debug(f"Checking DKMS log file: {log_file}")
                    with open(log_file, 'r', errors='replace') as f:
                        content = f.read()
                        warning_lines = [
                            line.strip() for line in content.splitlines() if "warning" in line.lower()]
                        if warning_lines:
                            warnings_found = True
                            # Collect up to 3 warnings per file
                            warning_messages.extend(warning_lines[:3])
                            logger.debug(
                                f"Found {len(warning_lines)} warnings in {log_file}")
                except Exception as e:
                    warning_messages.append(f"Error reading {log_file}: {e}")
                    logger.error(
                        f"Error reading DKMS log file {log_file}: {e}", exc_info=True)

            return warnings_found, warning_messages

        if graid_installed:
            warnings_found, warning_messages = check_warnings(graid_dir)
            results.append(
                f"Graid installation warnings: {colorize('No', Colors.GREEN) if not warnings_found else colorize('Yes', Colors.YELLOW)}")
            if warnings_found and warning_messages:
                results.append(
                    colorize("Sample warning messages:", Colors.YELLOW))
                for msg in warning_messages[:5]:  # Limit to 5 warnings
                    results.append(colorize(f"  - {msg}", Colors.YELLOW))
                if len(warning_messages) > 5:
                    results.append(
                        f"  ... and {len(warning_messages)-5} more warnings")
                add_issue(
                    "System", f"Graid DKMS installation has warnings", "MEDIUM")
                logger.warning(
                    f"Graid DKMS installation has {len(warning_messages)} warnings")
            else:
                logger.info(
                    "No warnings found in Graid DKMS installation logs")

        if nvidia_installed:
            warnings_found, warning_messages = check_warnings(nvidia_dir)
            results.append(
                f"NVIDIA installation warnings: {colorize('No', Colors.GREEN) if not warnings_found else colorize('Yes', Colors.YELLOW)}")
            if warnings_found and warning_messages:
                results.append(
                    colorize("Sample warning messages:", Colors.YELLOW))
                for msg in warning_messages[:5]:  # Limit to 5 warnings
                    results.append(colorize(f"  - {msg}", Colors.YELLOW))
                if len(warning_messages) > 5:
                    results.append(
                        f"  ... and {len(warning_messages)-5} more warnings")
                add_issue(
                    "System", f"NVIDIA DKMS installation has warnings", "MEDIUM")
                logger.warning(
                    f"NVIDIA DKMS installation has {len(warning_messages)} warnings")
            else:
                logger.info(
                    "No warnings found in NVIDIA DKMS installation logs")
    else:
        results.append(f"DKMS library directory not found: {dkms_lib_dir}")
        add_issue("System", f"Missing DKMS library directory", "MEDIUM")
        logger.warning(f"DKMS library directory not found: {dkms_lib_dir}")

    return results


def check_fstab():
    """
    Check fstab for correct Graid mount settings:
    - Verify required options for /dev/gdgXnY mounts
    """
    results = []
    results.append(
        colorize("Checking fstab for Graid mount settings...", Colors.BOLD))

    fstab_path = BASE_DIR / "basic_info" / "fstab"
    results.append(
        f"\n{colorize('Checking ' + str(fstab_path) + '...', Colors.BOLD)}")
    logger.info(f"Analyzing fstab configuration: {fstab_path}")

    if fstab_path.exists():
        try:
            graid_entries = []
            with open(fstab_path, 'r', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '/dev/gdg' in line:
                        graid_entries.append(line)
                        logger.debug(f"Found Graid entry in fstab: {line}")

            if graid_entries:
                results.append(
                    f"Found {len(graid_entries)} Graid mount entries:")
                logger.info(f"Found {len(graid_entries)} Graid mount entries")

                for entry in graid_entries:
                    # Check if it has the required mount options
                    required_options = [
                        'x-systemd.wants=graid.service', 'x-systemd.automount', 'nofail']
                    missing_options = [
                        option for option in required_options if option not in entry]

                    if not missing_options:
                        results.append(colorize(f"  ✓ {entry}", Colors.GREEN))
                        results.append(
                            colorize(f"    ✓ Has all required options", Colors.GREEN))
                        logger.info(
                            f"Graid entry has all required options: {entry}")
                    else:
                        results.append(colorize(f"  ✗ {entry}", Colors.RED))
                        results.append(
                            colorize(f"    ✗ Missing options: {', '.join(missing_options)}", Colors.RED))
                        mount_point = entry.split()[1] if len(
                            entry.split()) > 1 else "unknown"
                        add_issue(
                            "System", f"Graid mount entry for {mount_point} is missing required options: {', '.join(missing_options)}", "HIGH")
                        logger.error(
                            f"Graid mount entry for {mount_point} is missing required options: {', '.join(missing_options)}")
            else:
                results.append(
                    colorize("No Graid mount entries found in fstab", Colors.YELLOW))
                add_issue(
                    "System", "No Graid mount entries found in fstab", "LOW")
                logger.warning("No Graid mount entries found in fstab")
        except Exception as e:
            results.append(f"Error reading {fstab_path}: {e}")
            add_issue("System", f"Error reading fstab: {e}", "MEDIUM")
            logger.error(
                f"Error reading fstab {fstab_path}: {e}", exc_info=True)
    else:
        results.append(f"File not found: {fstab_path}")
        add_issue("System", f"Missing fstab file", "MEDIUM")
        logger.warning(f"fstab file not found: {fstab_path}")

    return results


def check_dmesg():
    """
    Check dmesg logs for important messages, particularly focusing on:
    - Errors and warnings related to hardware
    - GRAID-related messages
    - GPU/NVIDIA messages
    - NVMe-related messages
    - Kernel panics, oops, or assertions
    - Link Down events

    Saves detailed output to a separate file and returns summary for the main report.
    """
    results = []
    detailed_results = []
    results.append(
        colorize("Checking dmesg logs for important messages...", Colors.BOLD))
    detailed_results.append("=" * 80)
    detailed_results.append("DETAILED DMESG ANALYSIS REPORT")
    detailed_results.append("=" * 80)
    detailed_results.append("")
    logger.info("Starting dmesg log analysis")

    # Define paths to check for dmesg logs
    dmesg_log_paths = [
        BASE_DIR / "dmesg.log",
        BASE_DIR / "dmesg_journal.log",
        BASE_DIR / "logs" / "dmesg",
        BASE_DIR / "logs" / "dmesg_current.log"
    ]

    # Define patterns to search for
    error_patterns = [
        (r'\berror\b', 'Error messages', "HIGH"),
        (r'\bfail(ed|ure)?\b', 'Failure messages', "HIGH"),
        (r'\bwarn(ing)?\b', 'Warning messages', "MEDIUM"),
        (r'\boops\b', 'Kernel oops', "CRITICAL"),
        (r'\bpanic\b', 'Kernel panic', "CRITICAL"),
        (r'\bassert\b|\bassertion\b', 'Assertion failures', "CRITICAL"),
        (r'\bgraid\b', 'GRAID messages', "MEDIUM"),
        (r'\bnvidia\b', 'NVIDIA messages', "MEDIUM"),
        (r'\bnvme\b', 'NVMe messages', "MEDIUM"),
        (r'\btimeout\b', 'Timeout messages', "HIGH"),
        (r'\breset\b', 'Reset messages', "MEDIUM"),
        (r'\bnot responding\b', 'Not responding messages', "HIGH"),
        (r'\bcorrectable\b|\buncorrectable\b', 'ECC error messages', "HIGH"),
        (r'\bAER\b', 'PCIe AER messages', "HIGH"),  # Advanced Error Reporting
        # Added pattern for Link Down events
        (r'\blink down\b|\blinkdown\b', 'Link Down events', "HIGH")
    ]

    # Track counts for summary report
    message_counts = {pattern[1]: 0 for pattern in error_patterns}

    # Process each dmesg log
    for log_path in dmesg_log_paths:
        results.append(
            f"\n{colorize('Checking ' + str(log_path) + '...', Colors.BOLD)}")
        detailed_results.append(f"\n{'=' * 40}")
        detailed_results.append(f"CHECKING {log_path}")
        detailed_results.append(f"{'=' * 40}")
        logger.info(f"Analyzing dmesg log: {log_path}")

        if log_path.exists():
            try:
                # If file is compressed, handle differently
                if str(log_path).endswith('.gz'):
                    with gzip.open(log_path, 'rt', errors='replace') as f:
                        content = f.read()
                else:
                    with open(log_path, 'r', errors='replace') as f:
                        content = f.read()

                # Check for each pattern
                for pattern, description, severity in error_patterns:
                    matches = re.finditer(pattern, content, re.IGNORECASE)
                    matched_lines = []

                    for match in matches:
                        # Find the start of the line containing the match
                        line_start = content.rfind('\n', 0, match.start()) + 1
                        if line_start == 0:  # If no newline found, start from beginning
                            line_start = 0

                        # Find the end of the line
                        line_end = content.find('\n', match.end())
                        if line_end == -1:  # If no newline found, go to the end
                            line_end = len(content)

                        line = content[line_start:line_end].strip()
                        matched_lines.append(line)

                        # Add important messages as issues
                        if severity == "CRITICAL" or (severity == "HIGH" and ("error" in pattern or "fail" in pattern or "panic" in pattern or "link down" in pattern.lower())):
                            component = "System"
                            if "graid" in pattern.lower():
                                component = "GRAID"
                            elif "nvidia" in pattern.lower():
                                component = "NVIDIA"
                            elif "nvme" in pattern.lower():
                                component = "NVMe"

                            # Determine more specific component for Link Down events
                            if "link down" in pattern.lower() or "linkdown" in pattern.lower():
                                if "pcie" in line.lower() or "pci" in line.lower():
                                    component = "PCIe"
                                elif "nvme" in line.lower():
                                    component = "NVMe"
                                elif "eth" in line.lower() or "eno" in line.lower() or "network" in line.lower():
                                    component = "Network"

                            # Avoid duplicates
                            if not any(issue["description"].endswith(line) for issue in ALL_ISSUES):
                                add_issue(
                                    component, f"Dmesg {description.lower()[:-1]}: {line}", severity)
                                if severity == "CRITICAL":
                                    logger.critical(f"Found in dmesg: {line}")
                                else:
                                    logger.error(f"Found in dmesg: {line}")

                    # Update the count for this message type
                    message_counts[description] += len(matched_lines)

                    # Add to detailed report
                    if matched_lines:
                        detailed_results.append(
                            f"\n{description} - Found {len(matched_lines)}:")
                        log_level = logging.WARNING
                        if severity == "CRITICAL":
                            log_level = logging.CRITICAL
                        elif severity == "HIGH":
                            log_level = logging.ERROR

                        logger.log(
                            log_level, f"Found {len(matched_lines)} {description} in {log_path}")

                        for i, line in enumerate(matched_lines):
                            detailed_results.append(f"  {i+1}. {line}")
                            if i < 5:  # Log only first 5 examples
                                logger.log(log_level, f"  Example: {line}")

                        if len(matched_lines) > 5:
                            logger.log(
                                log_level, f"  ... and {len(matched_lines)-5} more not shown in log")

            except Exception as e:
                error_msg = f"Error reading {log_path}: {e}"
                results.append(error_msg)
                detailed_results.append(error_msg)
                add_issue("System", f"Error reading dmesg log: {e}", "MEDIUM")
                logger.error(
                    f"Error reading dmesg log {log_path}: {e}", exc_info=True)
        else:
            not_found_msg = f"Log file not found: {log_path}"
            results.append(not_found_msg)
            detailed_results.append(not_found_msg)
            logger.warning(f"Dmesg log file not found: {log_path}")

    # Write detailed results to file
    dmesg_details_file = Path(REPORT_FILE).parent / "dmesg_detailed_report.txt"
    try:
        with open(dmesg_details_file, 'w') as f:
            f.write("\n".join(detailed_results))

        # Add reference to detailed file in main report
        results.append(
            f"\nDetailed dmesg analysis saved to: {dmesg_details_file}")
        logger.info(f"Detailed dmesg analysis saved to: {dmesg_details_file}")
    except Exception as e:
        results.append(f"Error writing detailed dmesg report: {e}")
        add_issue("System", f"Error writing detailed dmesg report: {e}", "LOW")
        logger.error(
            f"Error writing detailed dmesg report: {e}", exc_info=True)

    # Add summary counts to main report
    results.append("\n" + colorize("DMESG Analysis Summary:", Colors.BOLD))
    found_any = False

    for description, count in message_counts.items():
        if count > 0:
            color_code = Colors.YELLOW
            log_level = logging.WARNING

            if "Error" in description or "Failure" in description or "panic" in description or "oops" in description or "Assertion" in description or "Link Down" in description:
                color_code = Colors.RED
                log_level = logging.ERROR

            results.append(
                colorize(f"Found {count} {description}", color_code))
            logger.log(log_level, f"Found {count} {description} in dmesg logs")
            found_any = True

    if not found_any:
        results.append(
            colorize("No matching messages found in dmesg logs", Colors.GREEN))
        logger.info("No matching messages found in dmesg logs")

    return results


def check_system_boot_time():
    """
    Check the system's last boot time by analyzing dmesg log files
    Specifically looks for the first message after reboot or the first message in logs
    """
    results = []
    results.append(colorize("Checking System Boot Time...", Colors.BOLD))
    logger.info("Analyzing system boot time from logs")

    boot_time = None
    boot_source = None

    # Log files to check
    log_files = [
        BASE_DIR / "dmesg.log",
        BASE_DIR / "dmesg_journal.log",
        BASE_DIR / "logs" / "dmesg",
    ]

    # First look specifically for reboot marker
    for log_path in log_files:
        if log_path.exists() and not boot_time:
            try:
                with open(log_path, 'r', errors='replace') as f:
                    content = f.read()

                    # Look for reboot marker and get timestamp of next line
                    reboot_pattern = r'-- Reboot --\s*\n(.*?)(?=\n)'
                    reboot_match = re.search(reboot_pattern, content)

                    if reboot_match:
                        next_line = reboot_match.group(1).strip()
                        logger.debug(
                            f"Found reboot marker in {log_path}, next line: {next_line}")

                        # Try to extract timestamp from the next line
                        timestamp_match = re.search(
                            r'\[([\d\-\.: ]+)\]', next_line)
                        if timestamp_match:
                            timestamp_str = timestamp_match.group(1).strip()

                            try:
                                # Try to parse as timestamp
                                if "-" in timestamp_str:  # Date format with hyphen
                                    boot_time = datetime.datetime.strptime(
                                        timestamp_str, "%Y-%m-%d %H:%M:%S")
                                    boot_source = f"After reboot marker in {log_path.name}"
                                    logger.info(
                                        f"Found boot time from reboot marker: {boot_time}")
                            except ValueError:
                                logger.warning(
                                    f"Failed to parse timestamp: {timestamp_str}")
                                pass
            except Exception as e:
                results.append(f"Error reading {log_path}: {e}")
                logger.error(
                    f"Error reading boot time from {log_path}: {e}", exc_info=True)

    # If reboot marker not found, try getting timestamp from kernel startup lines
    if not boot_time:
        kernel_start_patterns = [
            (r'\[([\d\-\.: ]+)\].*Linux version', "Linux version message"),
            (r'\[([\d\-\.: ]+)\].*Command line', "Kernel command line message"),
            (r'\[([\d\-\.: ]+)\].*Booting Linux', "Booting Linux message")
        ]

        for log_path in log_files:
            if log_path.exists() and not boot_time:
                try:
                    with open(log_path, 'r', errors='replace') as f:
                        content = f.read(10000)  # Read just the beginning part
                        logger.debug(
                            f"Searching for kernel startup messages in {log_path}")

                        for pattern, desc in kernel_start_patterns:
                            match = re.search(pattern, content)
                            if match:
                                timestamp_str = match.group(1).strip()
                                logger.debug(
                                    f"Found potential boot timestamp from {desc}: {timestamp_str}")

                                try:
                                    if "-" in timestamp_str:  # Date format with hyphen
                                        boot_time = datetime.datetime.strptime(
                                            timestamp_str, "%Y-%m-%d %H:%M:%S")
                                        boot_source = f"{desc} in {log_path.name}"
                                        logger.info(
                                            f"Found boot time from {desc}: {boot_time}")
                                        break
                                except ValueError:
                                    continue
                except Exception as e:
                    results.append(f"Error reading {log_path}: {e}")
                    logger.error(
                        f"Error reading kernel startup from {log_path}: {e}", exc_info=True)

    # If still not found, use system journal timestamps
    if not boot_time:
        for log_path in log_files:
            if log_path.exists() and not boot_time:
                try:
                    with open(log_path, 'r', errors='replace') as f:
                        # Read first few lines
                        first_lines = []
                        for _ in range(5):
                            line = f.readline().strip()
                            if line:
                                first_lines.append(line)

                        logger.debug(
                            f"Searching for journal timestamps in {log_path}")
                        for line in first_lines:
                            # Look for system journal timestamps (YYYY-MM-DD...)
                            timestamp_match = re.search(
                                r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', line)
                            if timestamp_match:
                                timestamp_str = timestamp_match.group(1)
                                try:
                                    boot_time = datetime.datetime.fromisoformat(
                                        timestamp_str)
                                    boot_source = f"First timestamp in {log_path.name}"
                                    logger.info(
                                        f"Found boot time from journal timestamp: {boot_time}")
                                    break
                                except ValueError:
                                    continue
                except Exception as e:
                    results.append(f"Error reading {log_path}: {e}")
                    logger.error(
                        f"Error reading journal timestamps from {log_path}: {e}", exc_info=True)

    # If all else fails, use first timestamp from dmesg with seconds since boot
    # and try to convert to absolute time using file time as reference
    if not boot_time:
        syslog_files = [
            BASE_DIR / "logs" / "syslog",
            BASE_DIR / "logs" / "syslog.1",
            BASE_DIR / "logs" / "messages",
        ]

        logger.debug("Attempting to use syslog timestamps as fallback")
        for log_path in syslog_files + log_files:
            if log_path.exists() and not boot_time:
                try:
                    file_mtime = datetime.datetime.fromtimestamp(
                        log_path.stat().st_mtime)
                    logger.debug(
                        f"File modification time for {log_path}: {file_mtime}")

                    with open(log_path, 'r', errors='replace') as f:
                        first_line = f.readline().strip()

                        # Look for timestamp at beginning of line
                        if "syslog" in str(log_path) or "messages" in str(log_path):
                            # System log format: MMM DD HH:MM:SS
                            timestamp_match = re.search(
                                r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})', first_line)
                            if timestamp_match:
                                timestamp_str = timestamp_match.group(1)
                                logger.debug(
                                    f"Found syslog timestamp: {timestamp_str}")
                                try:
                                    dt = datetime.datetime.strptime(
                                        timestamp_str, "%b %d %H:%M:%S")
                                    # Add current year
                                    dt = dt.replace(year=file_mtime.year)
                                    boot_time = dt
                                    boot_source = f"First entry in {log_path.name}"
                                    logger.info(
                                        f"Found boot time from syslog timestamp: {boot_time}")
                                    break
                                except ValueError:
                                    continue
                except Exception as e:
                    results.append(f"Error reading {log_path}: {e}")
                    logger.error(
                        f"Error reading syslog from {log_path}: {e}", exc_info=True)

    # Report boot time
    if boot_time:
        results.append(colorize(
            f"System last booted: {boot_time.strftime('%Y-%m-%d %H:%M:%S')} (Source: {boot_source})", Colors.GREEN))
        logger.info(
            f"System last booted: {boot_time.strftime('%Y-%m-%d %H:%M:%S')} (Source: {boot_source})")
    else:
        results.append(colorize(
            "Could not determine system boot time from available logs", Colors.YELLOW))
        add_issue("System", "Could not determine boot time", "LOW")
        logger.warning(
            "Could not determine system boot time from available logs")

    return results


def get_basic_info():
    """
    Get basic system information from basic.log
    """
    results = []
    results.append(colorize("Basic System Information", Colors.BOLD))

    basic_log = BASE_DIR / "basic.log"
    logger.info(f"Reading basic system information from: {basic_log}")
    if basic_log.exists():
        try:
            with open(basic_log, 'r', errors='replace') as f:
                basic_info = f.read().strip()
                results.append(basic_info)
                logger.debug("Successfully read basic system information")

                # Log some key system details if available
                if "kernel" in basic_info.lower():
                    kernel_match = re.search(
                        r'kernel[^\n]*', basic_info, re.IGNORECASE)
                    if kernel_match:
                        logger.info(f"Kernel info: {kernel_match.group(0)}")

                if "cpu" in basic_info.lower():
                    cpu_match = re.search(
                        r'cpu[^\n]*', basic_info, re.IGNORECASE)
                    if cpu_match:
                        logger.info(f"CPU info: {cpu_match.group(0)}")

                if "memory" in basic_info.lower() or "mem" in basic_info.lower():
                    mem_match = re.search(
                        r'(memory|mem)[^\n]*', basic_info, re.IGNORECASE)
                    if mem_match:
                        logger.info(f"Memory info: {mem_match.group(0)}")
        except Exception as e:
            results.append(f"Error reading basic.log: {e}")
            add_issue("System", f"Error reading basic information: {e}", "LOW")
            logger.error(
                f"Error reading basic information log {basic_log}: {e}", exc_info=True)
    else:
        results.append(f"Basic information log not found: {basic_log}")
        add_issue("System", f"Missing basic information log", "LOW")
        logger.warning(f"Basic information log not found: {basic_log}")

    return results


def check_graid_logs():
    """
    Check Graid-related logs for issues:
    - Filter logs for warning/critical events in the last 3 days
    - Check for errors, failures, and configuration issues
    """
    results = []
    results.append(colorize("Checking Graid-related logs...", Colors.BOLD))
    logger.info("Starting Graid logs analysis")

    # Get the timestamp from the last line of graid_server.log to determine three_days_ago
    graid_server_log = BASE_DIR / "graid_r" / "graid" / "graid_server.log"
    three_days_ago = None

    if graid_server_log.exists():
        try:
            # Read the last line of the file to get the latest timestamp
            last_line = ""
            with open(graid_server_log, 'r', errors='replace') as f:
                # Start from the end and read backwards until finding a non-empty line
                for line in reversed(list(f)):
                    if line.strip():
                        last_line = line.strip()
                        break

            # Parse the timestamp from the last line
            timestamp_match = re.search(r'\[([\d-]+ [\d:\.]+)\]', last_line)
            if timestamp_match:
                try:
                    # Parse timestamp without microseconds
                    timestamp_str = timestamp_match.group(1).split('.')[0]
                    log_date = datetime.datetime.strptime(
                        timestamp_str, "%Y-%m-%d %H:%M:%S")
                    three_days_ago = log_date - \
                        datetime.timedelta(days=7)  # Changed to 7 days
                    results.append(
                        f"Using reference timestamp from log: {log_date}")
                    results.append(
                        f"Checking for events after: {three_days_ago}")
                    logger.info(
                        f"Found reference timestamp from log: {log_date}")
                    logger.info(
                        f"Will check for events after: {three_days_ago}")
                except ValueError:
                    results.append(
                        f"Failed to parse timestamp from log: {timestamp_match.group(1)}")
                    add_issue(
                        "Graid", "Failed to parse timestamp from log", "LOW")
                    logger.warning(
                        f"Failed to parse timestamp from log: {timestamp_match.group(1)}")
        except Exception as e:
            results.append(
                f"Error reading last line from {graid_server_log}: {e}")
            add_issue(
                "Graid", f"Error reading graid_server.log: {e}", "MEDIUM")
            logger.error(
                f"Error reading last line from {graid_server_log}: {e}", exc_info=True)

    # If we couldn't determine three_days_ago from the log, use current time as fallback
    if three_days_ago is None:
        today = datetime.datetime.now()
        three_days_ago = today - \
            datetime.timedelta(days=7)  # Changed to 7 days
        results.append(f"Using current time as reference (fallback): {today}")
        results.append(f"Checking for events after: {three_days_ago}")
        logger.info(f"Using current time as reference (fallback): {today}")
        logger.info(f"Will check for events after: {three_days_ago}")

    # Helper function to parse dates from log lines with different formats
    def parse_date(line):
        date_formats = [
            "%Y-%m-%d %H:%M:%S",  # Standard format
            "%Y/%m/%d %H:%M:%S",  # Alternative format
            "%b %d %H:%M:%S %Y"   # Syslog format
        ]

        # Try to extract date from timestamp in brackets first
        timestamp_match = re.search(r'\[([\d-]+ [\d:\.]+)\]', line)
        if timestamp_match:
            timestamp_str = timestamp_match.group(1).split(
                '.')[0]  # Remove microseconds if present
            try:
                return datetime.datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass  # If this format fails, continue with other formats

        # Try standard formats
        for date_format in date_formats:
            try:
                # Try to extract date from beginning of line
                return datetime.datetime.strptime(line[:20].strip(), date_format)
            except ValueError:
                continue
        return None

    # 1. Check graid_server.log for warning or critical events
    graid_server_log = BASE_DIR / "graid_r" / "graid" / "graid_server.log"
    results.append(
        f"\n{colorize('Checking ' + str(graid_server_log) + ' for warning/critical events...', Colors.BOLD)}")
    logger.info(f"Analyzing {graid_server_log} for warning/critical events")

    if graid_server_log.exists():
        warning_critical_events = []
        try:
            with open(graid_server_log, 'r', errors='replace') as f:
                for line in f:
                    try:
                        # Parse date from log line
                        log_date = parse_date(line)
                        if log_date and log_date >= three_days_ago:
                            # Check for warning or critical level
                            lower_line = line.lower()
                            if "warning" in lower_line:
                                warning_critical_events.append(line.strip())
                                add_issue(
                                    "Graid", f"Warning event detected: {line.strip()}", "MEDIUM")
                                logger.warning(
                                    f"Warning event detected: {line.strip()}")
                            elif "critical" in lower_line:
                                warning_critical_events.append(line.strip())
                                add_issue(
                                    "Graid", f"Critical event detected: {line.strip()}", "HIGH")
                                logger.error(
                                    f"Critical event detected: {line.strip()}")
                            elif "error" in lower_line:
                                warning_critical_events.append(line.strip())
                                add_issue(
                                    "Graid", f"Error event detected: {line.strip()}", "HIGH")
                                logger.error(
                                    f"Error event detected: {line.strip()}")
                    except Exception:
                        pass  # Skip problematic lines
        except Exception as e:
            results.append(f"Error reading {graid_server_log}: {e}")
            add_issue(
                "Graid", f"Error reading graid_server.log: {e}", "MEDIUM")
            logger.error(
                f"Error reading {graid_server_log}: {e}", exc_info=True)

        if warning_critical_events:
            results.append(colorize(
                f"Found {len(warning_critical_events)} warning/critical/error events in last 7 days:", Colors.YELLOW))
            logger.warning(
                f"Found {len(warning_critical_events)} warning/critical/error events in last 7 days")
            # Limit to 5 events in report
            for event in warning_critical_events[:5]:
                results.append(colorize(f"  - {event}", Colors.YELLOW))
            if len(warning_critical_events) > 5:
                results.append(
                    f"  ... and {len(warning_critical_events)-5} more events")
                logger.warning(
                    f"... and {len(warning_critical_events)-5} more events not shown in report")
        else:
            results.append(
                colorize("No warning/critical/error events found in last 7 days", Colors.GREEN))
            logger.info(
                "No warning/critical/error events found in last 7 days")
    else:
        results.append(f"Log file not found: {graid_server_log}")
        add_issue("Graid", f"Missing log file: {graid_server_log}", "MEDIUM")
        logger.warning(f"Log file not found: {graid_server_log}")

    # 2. Check graid_core0.log and graid_core1.log for warning/critical events
    for core_log in ["graid_core0.log", "graid_core1.log"]:
        log_path = BASE_DIR / "graid_r" / "graid" / core_log
        results.append(
            f"\n{colorize('Checking ' + str(log_path) + ' for warning/critical events...', Colors.BOLD)}")
        logger.info(f"Analyzing {log_path} for warning/critical events")

        if log_path.exists():
            warning_critical_events = []
            try:
                with open(log_path, 'r', errors='replace') as f:
                    for line in f:
                        try:
                            # Parse date from log line
                            log_date = parse_date(line)
                            if log_date and log_date >= three_days_ago:
                                # Check for warning or critical level
                                lower_line = line.lower()
                                if "warning" in lower_line:
                                    warning_critical_events.append(
                                        line.strip())
                                    add_issue(
                                        "Graid", f"Warning event detected in {core_log}: {line.strip()}", "MEDIUM")
                                    logger.warning(
                                        f"Warning event detected in {core_log}: {line.strip()}")
                                elif "critical" in lower_line:
                                    warning_critical_events.append(
                                        line.strip())
                                    add_issue(
                                        "Graid", f"Critical event detected in {core_log}: {line.strip()}", "HIGH")
                                    logger.error(
                                        f"Critical event detected in {core_log}: {line.strip()}")
                                elif "error" in lower_line:
                                    warning_critical_events.append(
                                        line.strip())
                                    add_issue(
                                        "Graid", f"Error event detected in {core_log}: {line.strip()}", "HIGH")
                                    logger.error(
                                        f"Error event detected in {core_log}: {line.strip()}")
                        except Exception:
                            pass  # Skip problematic lines
            except Exception as e:
                results.append(f"Error reading {log_path}: {e}")
                add_issue("Graid", f"Error reading {core_log}: {e}", "MEDIUM")
                logger.error(f"Error reading {log_path}: {e}", exc_info=True)

            if warning_critical_events:
                results.append(colorize(
                    f"Found {len(warning_critical_events)} warning/critical/error events in last 7 days:", Colors.YELLOW))
                logger.warning(
                    f"Found {len(warning_critical_events)} warning/critical/error events in {core_log} in last 7 days")
                # Limit to 5 events in report
                for event in warning_critical_events[:5]:
                    results.append(colorize(f"  - {event}", Colors.YELLOW))
                if len(warning_critical_events) > 5:
                    results.append(
                        f"  ... and {len(warning_critical_events)-5} more events")
                    logger.warning(
                        f"... and {len(warning_critical_events)-5} more events not shown in report")
            else:
                results.append(
                    colorize("No warning/critical/error events found in last 7 days", Colors.GREEN))
                logger.info(
                    f"No warning/critical/error events found in {core_log} in last 7 days")
        else:
            results.append(f"Log file not found: {log_path}")
            add_issue("Graid", f"Missing log file: {log_path}", "LOW")
            logger.warning(f"Log file not found: {log_path}")

    # 3. Check upgrade_check.log for errors or fatal issues
    upgrade_check_log = BASE_DIR / "graid_r" / "graid" / "upgrade_check.log"
    results.append(
        f"\n{colorize('Checking ' + str(upgrade_check_log) + ' for errors or fatal issues...', Colors.BOLD)}")
    logger.info(f"Analyzing {upgrade_check_log} for errors or fatal issues")

    if upgrade_check_log.exists():
        errors_found = []
        try:
            with open(upgrade_check_log, 'r', errors='replace') as f:
                for line in f:
                    lower_line = line.lower()
                    if "error" in lower_line:
                        errors_found.append(line.strip())
                        add_issue(
                            "Graid", f"Error in upgrade check: {line.strip()}", "MEDIUM")
                        logger.warning(
                            f"Error in upgrade check: {line.strip()}")
                    elif "fatal" in lower_line:
                        errors_found.append(line.strip())
                        add_issue(
                            "Graid", f"Fatal issue in upgrade check: {line.strip()}", "HIGH")
                        logger.error(
                            f"Fatal issue in upgrade check: {line.strip()}")
        except Exception as e:
            results.append(f"Error reading {upgrade_check_log}: {e}")
            add_issue(
                "Graid", f"Error reading upgrade_check.log: {e}", "MEDIUM")
            logger.error(
                f"Error reading {upgrade_check_log}: {e}", exc_info=True)

        if errors_found:
            results.append(
                colorize(f"Found {len(errors_found)} error/fatal messages:", Colors.YELLOW))
            logger.warning(
                f"Found {len(errors_found)} error/fatal messages in upgrade check")
            for error in errors_found[:5]:  # Limit to 5 errors in report
                results.append(colorize(f"  - {error}", Colors.YELLOW))
            if len(errors_found) > 5:
                results.append(
                    f"  ... and {len(errors_found)-5} more error messages")
                logger.warning(
                    f"... and {len(errors_found)-5} more error messages not shown in report")
        else:
            results.append(
                colorize("No error/fatal messages found", Colors.GREEN))
            logger.info("No error/fatal messages found in upgrade check")
    else:
        results.append(f"Log file not found: {upgrade_check_log}")
        add_issue("Graid", f"Missing log file: {upgrade_check_log}", "LOW")
        logger.warning(f"Log file not found: {upgrade_check_log}")

    # 4. Check preinstaller.log for failed messages
    preinstaller_log = BASE_DIR / "graid_r" / \
        "graid-preinstaller" / "preinstaller.log"
    results.append(
        f"\n{colorize('Checking ' + str(preinstaller_log) + ' for failed messages...', Colors.BOLD)}")
    logger.info(f"Analyzing {preinstaller_log} for failed messages")

    if preinstaller_log.exists():
        failures_found = []
        try:
            with open(preinstaller_log, 'r', errors='replace') as f:
                for line in f:
                    if "failed" in line.lower():
                        failures_found.append(line.strip())
                        add_issue(
                            "Graid", f"Preinstaller failure: {line.strip()}", "HIGH")
                        logger.error(f"Preinstaller failure: {line.strip()}")
        except Exception as e:
            results.append(f"Error reading {preinstaller_log}: {e}")
            add_issue(
                "Graid", f"Error reading preinstaller.log: {e}", "MEDIUM")
            logger.error(
                f"Error reading {preinstaller_log}: {e}", exc_info=True)

        if failures_found:
            results.append(
                colorize(f"Found {len(failures_found)} failure messages:", Colors.RED))
            logger.error(
                f"Found {len(failures_found)} preinstaller failure messages")
            for failure in failures_found[:5]:  # Limit to 5 failures in report
                results.append(colorize(f"  - {failure}", Colors.RED))
            if len(failures_found) > 5:
                results.append(
                    f"  ... and {len(failures_found)-5} more failure messages")
                logger.error(
                    f"... and {len(failures_found)-5} more failure messages not shown in report")
        else:
            results.append(colorize("No failure messages found", Colors.GREEN))
            logger.info("No preinstaller failure messages found")
    else:
        results.append(f"Log file not found: {preinstaller_log}")
        add_issue("Graid", f"Missing log file: {preinstaller_log}", "LOW")
        logger.warning(f"Log file not found: {preinstaller_log}")

    # 5. Check error.tmp
    error_tmp = BASE_DIR / "graid_r" / "graid-preinstaller" / "error.tmp"
    results.append(
        f"\n{colorize('Checking ' + str(error_tmp) + '...', Colors.BOLD)}")
    logger.info(f"Analyzing {error_tmp}")

    if error_tmp.exists():
        try:
            with open(error_tmp, 'r', errors='replace') as f:
                content = f.read().strip()
                if content:
                    results.append(
                        colorize(f"Content of error.tmp:", Colors.RED))
                    if len(content) > 500:  # If content is too long, truncate it
                        results.append(
                            colorize(content[:500] + "... (truncated)", Colors.RED))
                        logger.error(
                            f"Content of error.tmp (truncated): {content[:500]}...")
                    else:
                        results.append(colorize(content, Colors.RED))
                        logger.error(f"Content of error.tmp: {content}")
                    add_issue(
                        "Graid", f"Error found in error.tmp: {content[:100]}...", "HIGH")
                else:
                    results.append(
                        colorize("error.tmp is empty", Colors.GREEN))
                    logger.info("error.tmp file exists but is empty")
        except Exception as e:
            results.append(f"Error reading {error_tmp}: {e}")
            add_issue("Graid", f"Error reading error.tmp: {e}", "MEDIUM")
            logger.error(f"Error reading {error_tmp}: {e}", exc_info=True)
    else:
        results.append(f"File not found: {error_tmp}")
        logger.debug(
            f"error.tmp file not found: {error_tmp} (this may be normal)")

    # 6. Check installer.log for failed messages
    installer_log = BASE_DIR / "graid_r" / "graid-installer" / "installer.log"
    results.append(
        f"\n{colorize('Checking ' + str(installer_log) + ' for failed messages...', Colors.BOLD)}")
    logger.info(f"Analyzing {installer_log} for failed messages")

    if installer_log.exists():
        failures_found = []
        try:
            with open(installer_log, 'r', errors='replace') as f:
                for line in f:
                    if "failed" in line.lower():
                        failures_found.append(line.strip())
                        add_issue(
                            "Graid", f"Installer failure: {line.strip()}", "HIGH")
                        logger.error(f"Installer failure: {line.strip()}")
        except Exception as e:
            results.append(f"Error reading {installer_log}: {e}")
            add_issue(
                "Graid", f"Error reading installer.log: {e}", "MEDIUM")
            logger.error(f"Error reading {installer_log}: {e}", exc_info=True)

        if failures_found:
            results.append(
                colorize(f"Found {len(failures_found)} failure messages:", Colors.RED))
            logger.error(
                f"Found {len(failures_found)} installer failure messages")
            for failure in failures_found[:5]:  # Limit to 5 failures in report
                results.append(colorize(f"  - {failure}", Colors.RED))
            if len(failures_found) > 5:
                results.append(
                    f"  ... and {len(failures_found)-5} more failure messages")
                logger.error(
                    f"... and {len(failures_found)-5} more failure messages not shown in report")
        else:
            results.append(colorize("No failure messages found", Colors.GREEN))
            logger.info("No installer failure messages found")
    else:
        results.append(f"Log file not found: {installer_log}")
        add_issue("Graid", f"Missing log file: {installer_log}", "LOW")
        logger.warning(f"Log file not found: {installer_log}")

    # 7. Check graid_basic_info.log for license and service status
    basic_info_log = BASE_DIR / "graid_r" / "graid_basic_info.log"
    results.append(
        f"\n{colorize('Checking ' + str(basic_info_log) + ' for license and service status...', Colors.BOLD)}")
    logger.info(f"Analyzing {basic_info_log} for license and service status")

    if basic_info_log.exists():
        license_applied = False
        service_graid_running = False
        service_graid_mgr_running = False

        try:
            with open(basic_info_log, 'r', errors='replace') as f:
                content = f.read()
                # Check for license applied
                if re.search(r'license.*applied', content, re.IGNORECASE):
                    license_applied = True
                    logger.info("Graid license is applied")
                else:
                    add_issue("Graid", "Graid license not applied", "HIGH")
                    logger.error("Graid license not applied")

                # Check for graid service running with the correct pattern
                graid_service_match = re.search(
                    r'graid\.service.*\n.*\n.*Active: active', content, re.IGNORECASE)
                if graid_service_match:
                    service_graid_running = True
                    logger.info("Graid service is running")
                else:
                    add_issue("Graid", "Graid service not running", "HIGH")
                    logger.error("Graid service not running")

                # Check for graid-mgr service running with the correct pattern
                graid_mgr_service_match = re.search(
                    r'graid-mgr\.service.*\n.*\n.*Active: active \(running\)', content, re.IGNORECASE)
                if graid_mgr_service_match:
                    service_graid_mgr_running = True
                    logger.info("Graid Manager service is running")
                else:
                    add_issue(
                        "Graid", "Graid Manager service not running", "MEDIUM")
                    logger.warning("Graid Manager service not running")
        except Exception as e:
            results.append(f"Error reading {basic_info_log}: {e}")
            add_issue("Graid", f"Error reading basic info log: {e}", "MEDIUM")
            logger.error(f"Error reading {basic_info_log}: {e}", exc_info=True)

        results.append(
            f"License applied: {colorize('Yes', Colors.GREEN) if license_applied else colorize('No', Colors.RED)}")
        results.append(
            f"Graid service running: {colorize('Yes', Colors.GREEN) if service_graid_running else colorize('No', Colors.RED)}")
        results.append(
            f"Graid-MGR service running: {colorize('Yes', Colors.GREEN) if service_graid_mgr_running else colorize('No', Colors.RED)}")
    else:
        results.append(f"Log file not found: {basic_info_log}")
        add_issue("Graid", f"Missing log file: {basic_info_log}", "MEDIUM")
        logger.warning(f"Log file not found: {basic_info_log}")

    # 8. Check check_cmdline.log for required parameters
    cmdline_log = BASE_DIR / "graid_r" / "check_cmdline.log"
    results.append(
        f"\n{colorize('Checking ' + str(cmdline_log) + ' for required parameters...', Colors.BOLD)}")
    logger.info(f"Analyzing {cmdline_log} for required kernel parameters")

    if cmdline_log.exists():
        iommu_param = False
        nvme_param = False
        try:
            with open(cmdline_log, 'r', errors='replace') as f:
                content = f.read()
                iommu_param = "iommu=pt" in content
                nvme_param = "nvme_core.multipath=Y" in content

                if not iommu_param:
                    add_issue(
                        "System", "Missing kernel parameter: iommu=pt", "HIGH")
                    logger.error("Missing required kernel parameter: iommu=pt")
                else:
                    logger.info("Kernel parameter iommu=pt is present")

                if not nvme_param:
                    add_issue(
                        "System", "Missing kernel parameter: nvme_core.multipath=Y", "HIGH")
                    logger.error(
                        "Missing required kernel parameter: nvme_core.multipath=Y")
                else:
                    logger.info(
                        "Kernel parameter nvme_core.multipath=Y is present")
        except Exception as e:
            results.append(f"Error reading {cmdline_log}: {e}")
            add_issue(
                "System", f"Error reading check_cmdline.log: {e}", "MEDIUM")
            logger.error(f"Error reading {cmdline_log}: {e}", exc_info=True)

        results.append(
            f"'iommu=pt' parameter found: {colorize('Yes', Colors.GREEN) if iommu_param else colorize('No', Colors.RED)}")
        results.append(
            f"'nvme_core.multipath=Y' parameter found: {colorize('Yes', Colors.GREEN) if nvme_param else colorize('No', Colors.RED)}")
    else:
        results.append(f"Log file not found: {cmdline_log}")
        add_issue("System", f"Missing log file: {cmdline_log}", "MEDIUM")
        logger.warning(f"Log file not found: {cmdline_log}")

    logger.info("Completed Graid logs analysis")
    return results


def main():
    """
    Main function to run all checks and save the report
    """
    logger.info("Starting GRAID System Analysis...")
    logger.info(f"Log directory: {BASE_DIR}")
    logger.info(f"Output report: {REPORT_FILE}")
    logger.info(f"Logging level: {args.log_level}")
    logger.info(f"Using colors: {USE_COLORS}")
    logger.info(f"Generate HTML report: {args.html}")

    # Verify log directory exists
    if not BASE_DIR.exists():
        logger.error(f"Log directory not found: {BASE_DIR}")
        sys.exit(1)

    # Create output directory if it doesn't exist
    output_dir = REPORT_FILE.parent
    if not output_dir.exists():
        try:
            output_dir.mkdir(parents=True)
            logger.info(f"Created output directory: {output_dir}")
        except Exception as e:
            logger.error(
                f"Error creating output directory: {e}", exc_info=True)
            sys.exit(1)

    # Create header for report
    all_results = []
    all_results.append("=" * 80)
    all_results.append(
        f"GRAID System Analysis Report - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    all_results.append("=" * 80)
    all_results.append("")
    logger.debug("Created report header")

    # First, get system basic info
    logger.info("Gathering basic system information")
    basic_info_results = get_basic_info()
    all_results.extend(basic_info_results)
    all_results.append("")
    logger.debug(
        f"Added {len(basic_info_results)} lines of basic system information")

    # Check system boot time
    logger.info("Checking system boot time")
    all_results.append("\n" + "=" * 80)
    all_results.append("System Boot Time Analysis")
    all_results.append("=" * 80)
    boot_time_results = check_system_boot_time()
    all_results.extend(boot_time_results)
    logger.debug(f"Added {len(boot_time_results)} lines of boot time analysis")

    # Define all check functions with their section titles
    check_functions = [
        ("1. GRAID Logs Check", check_graid_logs),
        ("2. NVIDIA Information Check", check_nv_info),
        ("3. NVMe Logs Check", check_nvme_logs),
        ("4. DKMS Status Check", check_dkms),
        ("5. FSTAB Configuration Check", check_fstab),
        ("6. DMESG Log Check", check_dmesg)
    ]
    logger.info(f"Defined {len(check_functions)} check functions to run")

    # Run each check and collect results
    for section_title, check_func in check_functions:
        all_results.append("\n" + "=" * 80)
        all_results.append(section_title)
        all_results.append("=" * 80)

        logger.info(f"Running {section_title}")
        start_time = datetime.datetime.now()

        try:
            section_results = check_func()
            all_results.extend(section_results)
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.info(
                f"Completed {section_title} in {duration:.2f} seconds, found {len(section_results)} results")
        except Exception as e:
            error_msg = f"Error running {section_title}: {e}"
            logger.error(error_msg, exc_info=True)
            all_results.append(colorize(error_msg, Colors.RED))
            add_issue("System", error_msg, "HIGH")
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.error(
                f"Failed {section_title} after {duration:.2f} seconds")

    # Generate executive summary now that we have all issues
    logger.info(f"Generating executive summary for {len(ALL_ISSUES)} issues")
    executive_summary = generate_executive_summary()

    # Add executive summary to the beginning of results
    full_results = ["=" * 80,
                    f"GRAID System Analysis Report - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    "=" * 80,
                    "",
                    executive_summary,
                    ""] + all_results
    logger.debug(f"Constructed full report with {len(full_results)} lines")

    # Write results to file
    try:
        with open(REPORT_FILE, 'w') as f:
            f.write("\n".join(full_results))
        logger.info(f"Analysis complete. Report saved to: {REPORT_FILE}")
        logger.info(f"Report size: {os.path.getsize(REPORT_FILE)} bytes")
    except Exception as e:
        logger.error(f"Error writing report to file: {e}", exc_info=True)
        logger.info("Printing report to console instead:")
        # Print first few lines of the report to avoid overwhelming the console
        for line in full_results[:100]:
            logger.info(line)
        if len(full_results) > 100:
            logger.info(
                f"... and {len(full_results) - 100} more lines not shown")

    # Generate HTML report if requested
    if args.html:
        html_report_file = REPORT_FILE.with_suffix('.html')
        try:
            logger.info("Generating HTML report")
            start_time = datetime.datetime.now()
            html_content = generate_html_report(full_results)
            with open(html_report_file, 'w') as f:
                f.write(html_content)
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            logger.info(f"HTML report saved to: {html_report_file}")
            logger.info(
                f"HTML report size: {os.path.getsize(html_report_file)} bytes")
            logger.info(f"HTML generation completed in {duration:.2f} seconds")
        except Exception as e:
            logger.error(f"Error generating HTML report: {e}", exc_info=True)

    # Log summary of issues by severity
    logger.info("\nSummary of findings:")
    if ALL_ISSUES:
        # Group issues by severity
        issues_by_severity = defaultdict(list)
        for issue in ALL_ISSUES:
            issues_by_severity[issue["severity"]].append(issue)

        # Log counts by severity
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = len(issues_by_severity[severity])
            if count > 0:
                if severity in ["CRITICAL", "HIGH"]:
                    logger.warning(f"{severity} issues: {count}")
                else:
                    logger.info(f"{severity} issues: {count}")

        # Log breakdown by component
        issues_by_component = defaultdict(list)
        for issue in ALL_ISSUES:
            issues_by_component[issue["component"]].append(issue)

        logger.info("\nIssues by component:")
        for component, issues in issues_by_component.items():
            logger.info(f"{component}: {len(issues)} issues")

        # Log critical and high issues
        if issues_by_severity["CRITICAL"] or issues_by_severity["HIGH"]:
            logger.warning("\nTop issues:")
            for severity in ["CRITICAL", "HIGH"]:
                for issue in issues_by_severity[severity]:
                    if severity == "CRITICAL":
                        logger.critical(
                            f"- {issue['component']}: {issue['description']}")
                    else:
                        logger.warning(
                            f"- {issue['component']}: {issue['description']}")
    else:
        logger.info("No issues found.")

    logger.info("GRAID System Analysis completed successfully")

    return 0  # Return success code


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.warning("\nAnalysis interrupted by user. Exiting...")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        logger.critical(f"\nUnexpected error: {e}", exc_info=True)
        logger.error(
            "If this issue persists, please check that the log directory structure is correct.")
        sys.exit(1)  # Return error code
