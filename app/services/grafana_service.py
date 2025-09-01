import requests
import json
import os
from typing import Dict, Any, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GrafanaService:
    def __init__(self):
        self.grafana_url = os.getenv("GRAFANA_URL", "http://localhost:3000")
        self.grafana_user = os.getenv("GRAFANA_USER", "admin")
        self.grafana_password = os.getenv("GRAFANA_PASSWORD", "admin")
        self.api_url = f"{self.grafana_url}/api"
        self.session = requests.Session()
        self.session.auth = (self.grafana_user, self.grafana_password)

    async def get_status(self) -> Dict[str, Any]:
        """Get Grafana connection status"""
        try:
            response = self.session.get(f"{self.api_url}/health")
            if response.status_code == 200:
                return {
                    "connected": True,
                    "version": response.json().get("version", "unknown"),
                    "database": response.json().get("database", "unknown")
                }
            else:
                return {"connected": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def setup_dashboard(self) -> Dict[str, Any]:
        """Setup Grafana dashboard and datasource"""
        try:
            # Check if we should setup PostgreSQL or SQLite
            database_url = os.getenv("DATABASE_URL", "")
            use_postgres = "postgresql" in database_url or "postgres" in database_url
            
            if use_postgres:
                # Setup PostgreSQL datasource
                datasource_result = await self._setup_postgres_datasource()
                if not datasource_result["success"]:
                    return datasource_result
            else:
                # For SQLite, we'll use a simple file-based approach or skip datasource
                datasource_result = {"success": True, "message": "SQLite mode - no external datasource needed"}

            # Setup dashboard
            dashboard_result = await self._setup_dashboard()
            if not dashboard_result["success"]:
                return dashboard_result

            return {
                "success": True,
                "message": "Grafana setup completed successfully",
                "datasource": datasource_result,
                "dashboard": dashboard_result,
                "database_type": "postgresql" if use_postgres else "sqlite"
            }

        except Exception as e:
            logger.error(f"Error setting up Grafana: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _setup_postgres_datasource(self) -> Dict[str, Any]:
        """Setup PostgreSQL datasource"""
        try:
            # Check if datasource already exists
            response = self.session.get(f"{self.api_url}/datasources/name/api_monitor_db")
            if response.status_code == 200:
                return {"success": True, "message": "Datasource already exists"}

            # Create datasource
            datasource_config = {
                "name": "api_monitor_db",
                "type": "postgres",
                "url": "postgres:5432",
                "database": "api_monitor",
                "user": "monitor_user",
                "secureJsonData": {
                    "password": "monitor_pass"
                },
                "jsonData": {
                    "sslmode": "disable",
                    "maxOpenConns": 100,
                    "maxIdleConns": 100,
                    "connMaxLifetime": 14400
                }
            }

            response = self.session.post(
                f"{self.api_url}/datasources",
                json=datasource_config,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code in [200, 201]:
                return {"success": True, "message": "Datasource created successfully"}
            else:
                return {"success": False, "error": f"Failed to create datasource: {response.text}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _setup_dashboard(self) -> Dict[str, Any]:
        """Setup monitoring dashboard"""
        try:
            dashboard_config = self._create_dashboard_config()
            
            response = self.session.post(
                f"{self.api_url}/dashboards/db",
                json={"dashboard": dashboard_config, "overwrite": True},
                headers={"Content-Type": "application/json"}
            )

            if response.status_code in [200, 201]:
                result = response.json()
                return {
                    "success": True,
                    "message": "Dashboard created successfully",
                    "url": f"{self.grafana_url}{result.get('url', '')}"
                }
            else:
                return {"success": False, "error": f"Failed to create dashboard: {response.text}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _create_dashboard_config(self) -> Dict[str, Any]:
        """Create dashboard configuration"""
        # Check database type to adjust queries
        database_url = os.getenv("DATABASE_URL", "")
        use_postgres = "postgresql" in database_url or "postgres" in database_url
        
        # Adjust SQL syntax for SQLite vs PostgreSQL
        if use_postgres:
            # PostgreSQL syntax
            heartbeat_query = """
                SELECT 
                    COUNT(*) as total_endpoints,
                    SUM(CASE WHEN last_status = true THEN 1 ELSE 0 END) as healthy_endpoints,
                    SUM(CASE WHEN last_status = false THEN 1 ELSE 0 END) as failed_endpoints
                FROM (
                    SELECT DISTINCT ON (config_id) 
                        config_id, 
                        is_success as last_status
                    FROM heartbeat_results 
                    ORDER BY config_id, timestamp DESC
                ) latest_results
            """
            response_time_query = """
                SELECT 
                    timestamp,
                    AVG(response_time_ms) as avg_response_time
                FROM heartbeat_results 
                WHERE timestamp >= NOW() - INTERVAL '24 hours'
                GROUP BY DATE_TRUNC('hour', timestamp)
                ORDER BY timestamp
            """
        else:
            # SQLite syntax
            heartbeat_query = """
                SELECT 
                    COUNT(*) as total_endpoints,
                    SUM(CASE WHEN last_status = 1 THEN 1 ELSE 0 END) as healthy_endpoints,
                    SUM(CASE WHEN last_status = 0 THEN 1 ELSE 0 END) as failed_endpoints
                FROM (
                    SELECT config_id, is_success as last_status
                    FROM heartbeat_results r1
                    WHERE timestamp = (
                        SELECT MAX(timestamp) 
                        FROM heartbeat_results r2 
                        WHERE r2.config_id = r1.config_id
                    )
                ) latest_results
            """
            response_time_query = """
                SELECT 
                    datetime(timestamp, 'start of hour') as timestamp,
                    AVG(response_time_ms) as avg_response_time
                FROM heartbeat_results 
                WHERE timestamp >= datetime('now', '-24 hours')
                GROUP BY datetime(timestamp, 'start of hour')
                ORDER BY timestamp
            """

        return {
            "title": "API Monitor Dashboard",
            "tags": ["api", "monitoring"],
            "timezone": "browser",
            "panels": [
                # Heartbeat Monitoring Panel
                {
                    "id": 1,
                    "title": "Heartbeat Monitoring",
                    "type": "stat",
                    "targets": [
                        {
                            "refId": "A",
                            "datasource": "api_monitor_db" if use_postgres else "grafana",
                            "rawQuery": True,
                            "rawSql": heartbeat_query
                        }
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "color": {
                                "mode": "thresholds"
                            },
                            "thresholds": {
                                "steps": [
                                    {"color": "green", "value": None},
                                    {"color": "red", "value": 1}
                                ]
                            }
                        }
                    },
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0}
                },
                # Response Time Panel
                {
                    "id": 2,
                    "title": "Average Response Time (Last 24h)",
                    "type": "timeseries",
                    "targets": [
                        {
                            "refId": "A",
                            "datasource": "api_monitor_db" if use_postgres else "grafana",
                            "rawQuery": True,
                            "rawSql": response_time_query
                        }
                    ],
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0}
                }
            ],
            "time": {
                "from": "now-24h",
                "to": "now"
            },
            "refresh": "30s"
        }

    async def create_custom_dashboard(self, dashboard_config: Dict[str, Any]) -> Dict[str, Any]:
        """Create a custom dashboard with provided configuration"""
        try:
            response = self.session.post(
                f"{self.api_url}/dashboards/db",
                json={"dashboard": dashboard_config, "overwrite": True},
                headers={"Content-Type": "application/json"}
            )

            if response.status_code in [200, 201]:
                result = response.json()
                return {
                    "success": True,
                    "message": "Custom dashboard created successfully",
                    "url": f"{self.grafana_url}{result.get('url', '')}"
                }
            else:
                return {"success": False, "error": f"Failed to create custom dashboard: {response.text}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_dashboards(self) -> Dict[str, Any]:
        """Get list of all dashboards"""
        try:
            response = self.session.get(f"{self.api_url}/search")
            if response.status_code == 200:
                return {"success": True, "dashboards": response.json()}
            else:
                return {"success": False, "error": f"Failed to get dashboards: {response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
