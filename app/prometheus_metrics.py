#!/usr/bin/env python3
"""
Prometheus Metrics Exporter for Integrated Monitor - API-Based
Provides metrics that match the actual API structure and endpoints
"""

import time
import threading
from prometheus_client import start_http_server, Gauge, Counter, Histogram, Summary, Info
from prometheus_client.core import REGISTRY
import requests
import json
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class APIBasedMetricsExporter:
    """Prometheus metrics exporter for Integrated Monitor - API-Based"""
    
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        
        # Initialize Prometheus metrics
        self._init_metrics()
        
        # Start metrics collection thread
        self.running = True
        self.collection_thread = threading.Thread(target=self._collect_metrics_loop)
        self.collection_thread.daemon = True
        self.collection_thread.start()
    
    def _init_metrics(self):
        """Initialize all Prometheus metrics based on actual API structure"""
        
        # System metrics
        self.system_info = Info('integrated_monitor_system', 'System information')
        self.system_info.info({
            'version': '1.0.0',
            'component': 'integrated_monitor',
            'api_based': 'true'
        })
        
        # Heartbeat API monitoring metrics (matches /api/heartbeat/* endpoints)
        self.heartbeat_status = Gauge(
            'heartbeat_status', 
            'Heartbeat endpoint status (1=up, 0=down)', 
            ['endpoint_name', 'endpoint_url', 'method', 'config_id']
        )
        self.heartbeat_response_time = Histogram(
            'heartbeat_response_time_seconds',
            'Heartbeat response time in seconds',
            ['endpoint_name', 'endpoint_url', 'config_id']
        )
        self.heartbeat_errors_total = Counter(
            'heartbeat_errors_total',
            'Total heartbeat errors',
            ['endpoint_name', 'error_type', 'config_id']
        )
        self.heartbeat_checks_total = Counter(
            'heartbeat_checks_total',
            'Total heartbeat checks performed',
            ['endpoint_name', 'status', 'config_id']
        )
        
        # S3 Bucket monitoring metrics (matches /api/s3/* endpoints)
        self.s3_bucket_status = Gauge(
            's3_bucket_status',
            'S3 bucket monitoring status (1=healthy, 0=unhealthy)',
            ['bucket_name', 'region', 'log_prefix', 'bucket_id']
        )
        self.s3_bucket_logs_count = Gauge(
            's3_bucket_logs_count',
            'Number of recent logs in S3 bucket',
            ['bucket_name', 'bucket_id']
        )
        self.s3_bucket_last_check = Gauge(
            's3_bucket_last_check_timestamp',
            'Timestamp of last S3 bucket check',
            ['bucket_name', 'bucket_id']
        )
        
        # S3 API monitoring metrics (matches /api/s3/api/* endpoints)
        self.s3_api_status = Gauge(
            's3_api_status',
            'S3 API monitoring status (1=up, 0=down)',
            ['api_name', 'api_url', 'method', 'bucket_id', 'config_id']
        )
        self.s3_api_response_time = Histogram(
            's3_api_response_time_seconds',
            'S3 API response time in seconds',
            ['api_name', 'api_url', 'config_id']
        )
        self.s3_api_errors_total = Counter(
            's3_api_errors_total',
            'Total S3 API errors',
            ['api_name', 'error_type', 'config_id']
        )
        self.s3_api_checks_total = Counter(
            's3_api_checks_total',
            'Total S3 API checks performed',
            ['api_name', 'status', 'config_id']
        )
        
        # Manual test metrics (matches /api/manual/* endpoints)
        self.manual_test_success = Gauge(
            'manual_test_success',
            'Manual test success status (1=success, 0=failure)',
            ['test_name', 'test_url', 'method', 'config_id']
        )
        self.manual_test_response_time = Histogram(
            'manual_test_response_time_seconds',
            'Manual test response time in seconds',
            ['test_name', 'test_url', 'config_id']
        )
        self.manual_test_errors_total = Counter(
            'manual_test_errors_total',
            'Total manual test errors',
            ['test_name', 'error_type', 'config_id']
        )
        self.manual_test_runs_total = Counter(
            'manual_test_runs_total',
            'Total manual test runs',
            ['test_name', 'status', 'config_id']
        )
        
        # System performance metrics (using custom names to avoid conflicts)
        self.app_cpu_seconds_total = Counter(
            'app_cpu_seconds_total',
            'Total user and system CPU time spent in seconds for this application'
        )
        self.app_resident_memory_bytes = Gauge(
            'app_resident_memory_bytes',
            'Resident memory size in bytes for this application'
        )
        
        # API endpoint metrics (matches actual API structure)
        self.api_endpoints_total = Gauge(
            'api_endpoints_total',
            'Total number of API endpoints by type',
            ['endpoint_type']
        )
        
        # Grafana integration metrics (matches /api/grafana/* endpoints)
        self.grafana_connection_status = Gauge(
            'grafana_connection_status',
            'Grafana connection status (1=connected, 0=disconnected)',
            ['grafana_url']
        )
        
        # Alert metrics
        self.alerts_firing = Gauge(
            'alerts_firing',
            'Number of firing alerts',
            ['alert_type', 'severity']
        )
    
    def _collect_metrics_loop(self):
        """Main metrics collection loop"""
        while self.running:
            try:
                self._collect_heartbeat_metrics()
                self._collect_s3_bucket_metrics()
                self._collect_s3_api_metrics()
                self._collect_manual_test_metrics()
                self._collect_system_metrics()
                self._collect_api_endpoint_counts()
                self._collect_grafana_metrics()
                
                logger.info("API-based metrics collection completed successfully")
                
            except Exception as e:
                logger.error(f"Error collecting API-based metrics: {e}")
            
            # Wait before next collection
            time.sleep(30)  # Collect every 30 seconds
    
    def _collect_heartbeat_metrics(self):
        """Collect heartbeat monitoring metrics from /api/heartbeat/* endpoints"""
        try:
            # Get heartbeat status from /api/heartbeat/status
            response = requests.get(f"{self.base_url}/api/heartbeat/status", timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                for endpoint in data:
                    endpoint_name = endpoint.get('name', 'unknown')
                    endpoint_url = endpoint.get('url', 'unknown')
                    method = endpoint.get('method', 'GET')
                    config_id = endpoint.get('id', 0)
                    last_status = endpoint.get('last_status', False)
                    response_time = endpoint.get('response_time_ms', 0) / 1000.0
                    
                    # Update status gauge
                    self.heartbeat_status.labels(
                        endpoint_name=endpoint_name,
                        endpoint_url=endpoint_url,
                        method=method,
                        config_id=config_id
                    ).set(1 if last_status else 0)
                    
                    # Update response time histogram
                    self.heartbeat_response_time.labels(
                        endpoint_name=endpoint_name,
                        endpoint_url=endpoint_url,
                        config_id=config_id
                    ).observe(response_time)
                    
                    # Update counters
                    self.heartbeat_checks_total.labels(
                        endpoint_name=endpoint_name,
                        status='success' if last_status else 'failure',
                        config_id=config_id
                    ).inc()
                    
                    if not last_status:
                        self.heartbeat_errors_total.labels(
                            endpoint_name=endpoint_name,
                            error_type='endpoint_down',
                            config_id=config_id
                        ).inc()
                
                logger.debug(f"Collected heartbeat metrics for {len(data)} endpoints")
                
        except Exception as e:
            logger.error(f"Error collecting heartbeat metrics: {e}")
    
    def _collect_s3_bucket_metrics(self):
        """Collect S3 bucket monitoring metrics from /api/s3/* endpoints"""
        try:
            # Get S3 status from /api/s3/status
            response = requests.get(f"{self.base_url}/api/s3/status", timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                for bucket in data:
                    bucket_name = bucket.get('bucket_name', 'unknown')
                    region = bucket.get('region', 'unknown')
                    log_prefix = bucket.get('log_prefix', 'unknown')
                    bucket_id = bucket.get('id', 0)
                    recent_logs_count = bucket.get('recent_logs_count', 0)
                    last_check = bucket.get('last_check')
                    is_healthy = bucket.get('is_healthy', True)
                    
                    # Update status gauge
                    self.s3_bucket_status.labels(
                        bucket_name=bucket_name,
                        region=region,
                        log_prefix=log_prefix,
                        bucket_id=bucket_id
                    ).set(1 if is_healthy else 0)
                    
                    # Update logs count
                    self.s3_bucket_logs_count.labels(
                        bucket_name=bucket_name,
                        bucket_id=bucket_id
                    ).set(recent_logs_count)
                    
                    # Update last check timestamp
                    if last_check:
                        try:
                            timestamp = datetime.fromisoformat(last_check.replace('Z', '+00:00')).timestamp()
                            self.s3_bucket_last_check.labels(
                                bucket_name=bucket_name,
                                bucket_id=bucket_id
                            ).set(timestamp)
                        except:
                            pass
                
                logger.debug(f"Collected S3 bucket metrics for {len(data)} buckets")
                
        except Exception as e:
            logger.error(f"Error collecting S3 bucket metrics: {e}")
    
    def _collect_s3_api_metrics(self):
        """Collect S3 API monitoring metrics from /api/s3/api/* endpoints"""
        try:
            # Get S3 API status from /api/s3/api/status
            response = requests.get(f"{self.base_url}/api/s3/api/status", timeout=10)
            if response.status_code == 200:
                data = response.json()
                api_status = data.get('api_status', {})
                
                for api_name, status_info in api_status.items():
                    api_url = status_info.get('url', 'unknown')
                    method = status_info.get('method', 'GET')
                    bucket_id = status_info.get('bucket_id', 0)
                    config_id = status_info.get('id', 0)
                    status = status_info.get('status', 'unknown')
                    last_check = status_info.get('last_check')
                    
                    # Update status gauge
                    status_value = 1 if status == 'up' else 0
                    self.s3_api_status.labels(
                        api_name=api_name,
                        api_url=api_url,
                        method=method,
                        bucket_id=bucket_id,
                        config_id=config_id
                    ).set(status_value)
                    
                    # Update counters
                    self.s3_api_checks_total.labels(
                        api_name=api_name,
                        status=status,
                        config_id=config_id
                    ).inc()
                    
                    if status != 'up':
                        self.s3_api_errors_total.labels(
                            api_name=api_name,
                            error_type='api_down',
                            config_id=config_id
                        ).inc()
                
                logger.debug(f"Collected S3 API metrics for {len(api_status)} APIs")
                
        except Exception as e:
            logger.error(f"Error collecting S3 API metrics: {e}")
    
    def _collect_manual_test_metrics(self):
        """Collect manual test metrics from /api/manual/* endpoints"""
        try:
            # Get manual test results from /api/manual/results
            response = requests.get(f"{self.base_url}/api/manual/results?hours=1", timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                for result in data:
                    config_id = result.get('config_id', 0)
                    is_success = result.get('is_success', False)
                    response_time = result.get('response_time_ms', 0) / 1000.0
                    
                    # Get endpoint details from config
                    try:
                        config_response = requests.get(f"{self.base_url}/api/manual/endpoints/{config_id}", timeout=5)
                        if config_response.status_code == 200:
                            config_data = config_response.json().get('endpoint', {})
                            test_name = config_data.get('name', 'unknown')
                            test_url = config_data.get('url', 'unknown')
                            method = config_data.get('method', 'GET')
                            
                            # Update success gauge
                            self.manual_test_success.labels(
                                test_name=test_name,
                                test_url=test_url,
                                method=method,
                                config_id=config_id
                            ).set(1 if is_success else 0)
                            
                            # Update response time histogram
                            self.manual_test_response_time.labels(
                                test_name=test_name,
                                test_url=test_url,
                                config_id=config_id
                            ).observe(response_time)
                            
                            # Update run counter
                            self.manual_test_runs_total.labels(
                                test_name=test_name,
                                status='success' if is_success else 'failure',
                                config_id=config_id
                            ).inc()
                            
                            if not is_success:
                                self.manual_test_errors_total.labels(
                                    test_name=test_name,
                                    error_type='test_failure',
                                    config_id=config_id
                                ).inc()
                    except:
                        pass
                
                logger.debug(f"Collected manual test metrics for {len(data)} results")
                
        except Exception as e:
            logger.error(f"Error collecting manual test metrics: {e}")
    
    def _collect_system_metrics(self):
        """Collect system performance metrics"""
        try:
            import psutil
            import os
            
            # CPU time
            process = psutil.Process(os.getpid())
            cpu_times = process.cpu_times()
            self.app_cpu_seconds_total.inc(cpu_times.user + cpu_times.system)
            
            # Memory usage
            memory_info = process.memory_info()
            self.app_resident_memory_bytes.set(memory_info.rss)
            
            logger.debug("Collected system metrics")
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
    
    def _collect_api_endpoint_counts(self):
        """Collect API endpoint counts from /api/stats"""
        try:
            response = requests.get(f"{self.base_url}/api/stats", timeout=10)
            if response.status_code == 200:
                data = response.json()
                stats = data.get('stats', {})
                
                # Update endpoint counts
                self.api_endpoints_total.labels(endpoint_type='heartbeat').set(
                    stats.get('heartbeat_endpoints', 0)
                )
                self.api_endpoints_total.labels(endpoint_type='s3_api').set(
                    stats.get('s3_api_configs', 0)
                )
                self.api_endpoints_total.labels(endpoint_type='manual').set(
                    stats.get('manual_endpoints', 0)
                )
                self.api_endpoints_total.labels(endpoint_type='s3_bucket').set(
                    stats.get('s3_buckets', 0)
                )
                
                logger.debug("Collected API endpoint counts")
                
        except Exception as e:
            logger.error(f"Error collecting API endpoint counts: {e}")
    
    def _collect_grafana_metrics(self):
        """Collect Grafana integration metrics from /api/grafana/* endpoints"""
        try:
            response = requests.get(f"{self.base_url}/api/grafana/status", timeout=10)
            if response.status_code == 200:
                data = response.json()
                connected = data.get('connected', False)
                grafana_url = data.get('url', 'unknown')
                
                self.grafana_connection_status.labels(
                    grafana_url=grafana_url
                ).set(1 if connected else 0)
                
                logger.debug("Collected Grafana metrics")
                
        except Exception as e:
            logger.error(f"Error collecting Grafana metrics: {e}")
    
    def stop(self):
        """Stop the metrics collection"""
        self.running = False
        if self.collection_thread.is_alive():
            self.collection_thread.join(timeout=5)

def main():
    """Main function to start the Prometheus metrics server"""
    import argparse
    
    parser = argparse.ArgumentParser(description='API-Based Prometheus Metrics Exporter for Integrated Monitor')
    parser.add_argument('--port', type=int, default=9090, help='Port to expose metrics on (default: 9090)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--base-url', default='http://localhost:8000', help='Base URL of the monitoring service')
    
    args = parser.parse_args()
    
    # Start the metrics server
    start_http_server(args.port, addr=args.host)
    logger.info(f"API-based Prometheus metrics server started on {args.host}:{args.port}")
    
    # Initialize and start metrics collection
    metrics = APIBasedMetricsExporter(base_url=args.base_url)
    logger.info(f"API-based metrics collection started for {args.base_url}")
    
    try:
        # Keep the server running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down API-based metrics server...")
        metrics.stop()

if __name__ == "__main__":
    main()
