import base64
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from googleapiclient.discovery import build
import google.auth
from google.cloud import storage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_maintenance_schedule(request: Any) -> str:
    """
    Cloud Function entry point.
    Triggered by Cloud Scheduler (HTTP).
    
    Args:
        request: The request object.
    
    Returns:
        JSON string response.
    """
    try:
        # 1. Configuration
        target_projects_str = os.environ.get('TARGET_PROJECTS', '')
        output_bucket = os.environ.get('OUTPUT_BUCKET')
        
        if not target_projects_str:
            # Fallback to current project if not specified
            _, project_id = google.auth.default()
            target_projects = [project_id]
            logger.info(f"TARGET_PROJECTS not set. Defaulting to current project: {project_id}")
        else:
            target_projects = [p.strip() for p in target_projects_str.split(',') if p.strip()]

        if not output_bucket:
            logger.warning("OUTPUT_BUCKET not set. Results will only be logged.")

        # 2. Service Setup
        sql_service = build('sqladmin', 'v1beta4')
        storage_client = storage.Client() if output_bucket else None

        all_maintenance_events = []
        report_date = datetime.utcnow().strftime("%Y-%m-%d")

        # 3. Discovery & Detection
        for project in target_projects:
            logger.info(f"Scanning project: {project}")
            try:
                request_list = sql_service.instances().list(project=project)
                while request_list is not None:
                    response = request_list.execute()
                    instances = response.get('items', [])
                    
                    for instance in instances:
                        maintenance_event = process_instance(instance)
                        if maintenance_event:
                            maintenance_event['project_id'] = project
                            all_maintenance_events.append(maintenance_event)
                    
                    request_list = sql_service.instances().list_next(previous_request=request_list, previous_response=response)
            except Exception as e:
                logger.error(f"Error scanning project {project}: {e}")

        # 4. Reporting (Output)
        report = {
            "report_date": report_date,
            "upcoming_maintenance": all_maintenance_events
        }
        
        report_json = json.dumps(report, indent=2)
        logger.info(f"Report generated:\n{report_json}")

        if storage_client and output_bucket:
            bucket = storage_client.bucket(output_bucket)
            blob_name = f"maintenance-reports/{report_date}.json"
            blob = bucket.blob(blob_name)
            blob.upload_from_string(report_json, content_type='application/json')
            logger.info(f"Report uploaded to gs://{output_bucket}/{blob_name}")

        return report_json

    except Exception as e:
        logger.exception("Fatal error in check_maintenance_schedule")
        return json.dumps({"error": str(e)}), 500

def process_instance(instance: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Analyzes a Cloud SQL instance to determine if maintenance is scheduled
    and classifies the update type.
    """
    name = instance.get('name')
    # Check for maintenanceScheduled
    maintenance_scheduled = instance.get('maintenanceScheduled', False)
    
    # NOTE: The API might return this info in specific fields.
    # We follow the spec's heuristic and fields.
    
    if not maintenance_scheduled:
        return None

    # Gather Metadata
    database_installed_version = instance.get('databaseInstalledVersion', 'UNKNOWN')
    
    # Spec Logic: Fetch 'availableMaintenanceVersions'
    # Use .get() loosely as this field might be specific to certain contexts or API versions
    available_versions = instance.get('availableMaintenanceVersions', [])
    
    # If explicitly just one version or we take the first/latest?
    # Spec implies direct comparison. Let's assume list and take latest or first.
    # If missing, we can't classify reliably, but will default to UNKNOWN or guess.
    
    target_version = None
    if available_versions and isinstance(available_versions, list) and len(available_versions) > 0:
         # Assuming the list contains strings of versions
         target_version = available_versions[0] 
    
    update_type = "UNKNOWN"
    description = "Maintenance scheduled but version details unavailable."
    
    if target_version:
        # Heuristic: Compare base version string (ignoring build suffixes starting with '.')
        # User Example: 
        #   Installed: POSTGRES_12_8
        #   Target:    POSTGRES_12_10.R20220331.02_01
        
        # We process both distinct parts just in case Installed also has build info.
        installed_base = database_installed_version.split('.')[0]
        target_base = target_version.split('.')[0]
        
        if installed_base == target_base:
            update_type = "OS_PATCH"
            description = "Routine system update. No version change detected."
        else:
            update_type = "MINOR_VERSION_UPGRADE"
            description = f"Upgrade likely. Current: {installed_base} -> Target: {target_base}"

    # Construct Payload Item
    # Spec 5.2 output format
    
    window_start = "PENDING_SCHEDULING" # Default if not found
    
    # Try to find specific maintenance info
    # Some APIs expose it under maintenanceScheduled details.
    
    return {
        "instance": name,
        "window_start": window_start, # specific time might not be in standard list response
        "current_version": database_installed_version,
        "estimated_update_type": update_type,
        "description": description
    }
