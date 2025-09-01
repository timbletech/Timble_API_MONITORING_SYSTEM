"""
Heartbeat Monitor Service

This service provides automated health monitoring for API endpoints.
It continuously checks configured endpoints at specified intervals and
stores results for analysis and alerting.

Features:
- Automated health checks with configurable intervals
- Response time tracking
- Status code validation
- Response content validation
- Historical data storage
- Real-time status reporting
- Email alert throttling (1 minute gap between alerts for same endpoint)

Author: Integrated Monitor Team
Version: 1.0.1
"""

import requests
import time
import threading
import schedule
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from app.db.session import SessionLocal
from app.db.models import APIHeartbeatConfig, HeartbeatResult, APIHeartbeatConfigCreate
from app.services.email_service import EmailService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HeartbeatMonitor:
    def __init__(self):
        self.monitoring = False
        self.monitoring_thread = None
        self.email_service = EmailService()
        # Track previous status to detect recovery
        self.previous_status = {}  # {endpoint_id: previous_status}
        # Track last email alert time for each endpoint to prevent spam
        self.last_alert_time = {}  # {endpoint_id: datetime}

    async def add_endpoint(self, api_config: APIHeartbeatConfigCreate) -> Dict[str, Any]:
        """Add a new API endpoint for heartbeat monitoring"""
        db = SessionLocal()
        try:
            # Validate the configuration
            if not api_config.name or not api_config.url:
                return {"success": False, "error": "Name and URL are required"}
            
            # Check if endpoint with same name already exists
            existing = db.query(APIHeartbeatConfig).filter(
                APIHeartbeatConfig.name == api_config.name,
                APIHeartbeatConfig.is_active == True
            ).first()
            
            if existing:
                return {"success": False, "error": "Endpoint with this name already exists"}
            
            db_config = APIHeartbeatConfig(
                name=api_config.name,
                url=api_config.url,
                method=api_config.method,
                headers=api_config.headers,
                body=api_config.body,
                expected_status=api_config.expected_status,
                expected_response=api_config.expected_response,
                interval_minutes=api_config.interval_minutes,
                timeout_seconds=api_config.timeout_seconds
            )
            db.add(db_config)
            db.commit()
            db.refresh(db_config)
            
            logger.info(f"Added heartbeat endpoint: {api_config.name}")
            return {"success": True, "id": db_config.id, "message": "Endpoint added successfully"}
        except Exception as e:
            db.rollback()
            logger.error(f"Error adding heartbeat endpoint: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    async def update_endpoint(self, endpoint_id: int, api_config: APIHeartbeatConfigCreate) -> Dict[str, Any]:
        """Update an existing API endpoint for heartbeat monitoring"""
        db = SessionLocal()
        try:
            db_config = db.query(APIHeartbeatConfig).filter(APIHeartbeatConfig.id == endpoint_id).first()
            
            if not db_config:
                return {"success": False, "error": "Endpoint not found"}
            
            # Update the configuration
            db_config.name = api_config.name
            db_config.url = api_config.url
            db_config.method = api_config.method
            db_config.headers = api_config.headers
            db_config.body = api_config.body
            db_config.expected_status = api_config.expected_status
            db_config.expected_response = api_config.expected_response
            db_config.interval_minutes = api_config.interval_minutes
            db_config.timeout_seconds = api_config.timeout_seconds
            
            db.commit()
            
            # Trigger an immediate check
            self.check_endpoint(db_config)
            
            logger.info(f"Updated heartbeat endpoint: {api_config.name}")
            return {"success": True, "message": "Endpoint updated and checked successfully"}
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating heartbeat endpoint: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def should_send_alert(self, endpoint_id: int) -> bool:
        """Check if enough time has passed since last alert for this endpoint"""
        current_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))  # IST
        last_alert = self.last_alert_time.get(endpoint_id)
        
        if last_alert is None:
            return True
        
        # Check if at least 1 minute has passed since last alert
        time_diff = current_time - last_alert
        return time_diff.total_seconds() >= 60  # 1 minute = 60 seconds

    def update_last_alert_time(self, endpoint_id: int):
        """Update the last alert time for an endpoint"""
        self.last_alert_time[endpoint_id] = datetime.now(timezone(timedelta(hours=5, minutes=30)))

    async def get_status(self) -> List[Dict[str, Any]]:
        """Get status of all heartbeat monitored endpoints"""
        db = SessionLocal()
        try:
            configs = db.query(APIHeartbeatConfig).filter(APIHeartbeatConfig.is_active == True).all()
            status_list = []
            
            for config in configs:
                # Get latest result
                latest_result = db.query(HeartbeatResult).filter(
                    HeartbeatResult.config_id == config.id
                ).order_by(HeartbeatResult.timestamp.desc()).first()
                
                status = {
                    "id": config.id,
                    "name": config.name,
                    "url": config.url,
                    "method": config.method,
                    "headers": config.headers,
                    "body": config.body,
                    "expected_status": config.expected_status,
                    "expected_response": config.expected_response,
                    "interval_minutes": config.interval_minutes,
                    "timeout_seconds": config.timeout_seconds,
                    "is_active": config.is_active,
                    "last_check": latest_result.timestamp if latest_result else None,
                    "last_status": latest_result.is_success if latest_result else None,
                    "last_response_time": latest_result.response_time_ms if latest_result else None,
                    "last_status_code": latest_result.status_code if latest_result else None,
                    "last_error_message": latest_result.error_message if latest_result else None
                }
                status_list.append(status)
            
            return status_list
        except Exception as e:
            logger.error(f"Error getting heartbeat status: {str(e)}")
            return []
        finally:
            db.close()

    async def get_history(self, endpoint_id: int, hours: int = 24) -> List[Dict[str, Any]]:
        """Get heartbeat history for a specific endpoint"""
        db = SessionLocal()
        try:
            # IST timezone (UTC+5:30)
            ist_timezone = timezone(timedelta(hours=5, minutes=30))
            since_time = datetime.now(ist_timezone) - timedelta(hours=hours)
            results = db.query(HeartbeatResult).filter(
                HeartbeatResult.config_id == endpoint_id,
                HeartbeatResult.timestamp >= since_time
            ).order_by(HeartbeatResult.timestamp.desc()).all()
            
            return [
                {
                    "id": result.id,
                    "status_code": result.status_code,
                    "response_time_ms": result.response_time_ms,
                    "is_success": result.is_success,
                    "error_message": result.error_message,
                    "response_body": result.response_body,
                    "timestamp": result.timestamp
                }
                for result in results
            ]
        except Exception as e:
            logger.error(f"Error getting heartbeat history: {str(e)}")
            return []
        finally:
            db.close()

    async def get_all_endpoints(self) -> List[Dict[str, Any]]:
        """Get all heartbeat monitoring endpoints"""
        db = SessionLocal()
        try:
            configs = db.query(APIHeartbeatConfig).filter(APIHeartbeatConfig.is_active == True).all()
            
            return [
                {
                    "id": config.id,
                    "name": config.name,
                    "url": config.url,
                    "method": config.method,
                    "headers": config.headers,
                    "body": config.body,
                    "expected_status": config.expected_status,
                    "expected_response": config.expected_response,
                    "interval_minutes": config.interval_minutes,
                    "timeout_seconds": config.timeout_seconds,
                    "is_active": config.is_active,
                    "created_at": config.created_at,
                    "updated_at": config.updated_at
                }
                for config in configs
            ]
        except Exception as e:
            logger.error(f"Error getting all heartbeat endpoints: {str(e)}")
            return []
        finally:
            db.close()

    async def get_endpoint(self, endpoint_id: int) -> Dict[str, Any]:
        """Get a specific heartbeat endpoint by ID"""
        db = SessionLocal()
        try:
            config = db.query(APIHeartbeatConfig).filter(
                APIHeartbeatConfig.id == endpoint_id,
                APIHeartbeatConfig.is_active == True
            ).first()
            
            if not config:
                return {"success": False, "error": "Endpoint not found"}
            
            return {
                "success": True,
                "endpoint": {
                    "id": config.id,
                    "name": config.name,
                    "url": config.url,
                    "method": config.method,
                    "headers": config.headers,
                    "body": config.body,
                    "expected_status": config.expected_status,
                    "expected_response": config.expected_response,
                    "interval_minutes": config.interval_minutes,
                    "timeout_seconds": config.timeout_seconds,
                    "is_active": config.is_active,
                    "created_at": config.created_at,
                    "updated_at": config.updated_at
                }
            }
        except Exception as e:
            logger.error(f"Error getting heartbeat endpoint {endpoint_id}: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    async def delete_endpoint(self, endpoint_id: int) -> Dict[str, Any]:
        """Delete a heartbeat monitoring endpoint (soft delete)"""
        db = SessionLocal()
        try:
            config = db.query(APIHeartbeatConfig).filter(APIHeartbeatConfig.id == endpoint_id).first()
            
            if not config:
                return {"success": False, "error": "Endpoint not found"}
            
            # Soft delete by setting is_active to False
            config.is_active = False
            db.commit()
            
            # Clear tracking data for this endpoint
            if endpoint_id in self.previous_status:
                del self.previous_status[endpoint_id]
            if endpoint_id in self.last_alert_time:
                del self.last_alert_time[endpoint_id]
            
            logger.info(f"Deleted heartbeat endpoint: {config.name}")
            return {"success": True, "message": "Endpoint deleted successfully"}
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting heartbeat endpoint: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    async def test_endpoint(self, endpoint_id: int) -> Dict[str, Any]:
        """Manually test a heartbeat endpoint"""
        db = SessionLocal()
        try:
            config = db.query(APIHeartbeatConfig).filter(
                APIHeartbeatConfig.id == endpoint_id,
                APIHeartbeatConfig.is_active == True
            ).first()
            
            if not config:
                return {"success": False, "error": "Endpoint not found or inactive"}
            
            # Perform the test
            start_time = time.time()
            is_success = False
            status_code = None
            error_message = None
            response_body = None
            
            try:
                # Prepare request
                headers = config.headers or {}
                data = config.body if config.method in ['POST', 'PUT', 'PATCH'] else None
                
                # Add User-Agent if not present
                if 'User-Agent' not in headers:
                    headers['User-Agent'] = 'HeartbeatMonitor/1.0'
                
                response = requests.request(
                    method=config.method,
                    url=config.url,
                    headers=headers,
                    data=data,
                    timeout=config.timeout_seconds,
                    allow_redirects=True
                )
                
                status_code = response.status_code
                response_body = response.text[:1000]  # Limit response body size
                
                # Check if test was successful based on expected status and response
                is_success = (
                    status_code in config.expected_status and
                    (not config.expected_response or config.expected_response in response_body)
                )
                
            except requests.exceptions.Timeout:
                error_message = "Request timeout"
            except requests.exceptions.ConnectionError:
                error_message = "Connection error"
            except Exception as e:
                error_message = str(e)
            
            response_time_ms = (time.time() - start_time) * 1000
            
            # Create IST timestamp
            ist_timezone = timezone(timedelta(hours=5, minutes=30))
            ist_timestamp = datetime.now(ist_timezone)
            
            # Store result
            result = HeartbeatResult(
                config_id=config.id,
                status_code=status_code,
                response_time_ms=response_time_ms,
                is_success=is_success,
                error_message=error_message,
                response_body=response_body,
                timestamp=ist_timestamp
            )
            
            db.add(result)
            db.commit()
            
            # Check if status is not 200 and send email alert for manual tests (with throttling)
            if status_code != 200:
                logger.warning(f"Manual test failed with status code {status_code} for {config.name}")
                
                # Check if we should send alert (respecting 1-minute gap)
                if self.should_send_alert(endpoint_id):
                    logger.info(f"Sending email alert for manual test failure of {config.name}")
                    try:
                        # Send failure alert
                        email_result = self.email_service.send_heartbeat_alert(
                            endpoint_name=config.name,
                            endpoint_url=config.url,
                            method=config.method,
                            status_code=status_code,
                            response_time_ms=response_time_ms,
                            error_message=error_message
                        )
                        
                        if email_result["success"]:
                            self.update_last_alert_time(endpoint_id)
                            logger.info(f"Email alert sent for manual test failure of {config.name}")
                        else:
                            logger.error(f"Failed to send email alert for manual test failure of {config.name}: {email_result.get('error', 'Unknown error')}")
                            
                    except Exception as e:
                        logger.error(f"Error sending email alert for manual test failure of {config.name}: {str(e)}")
                else:
                    last_alert = self.last_alert_time.get(endpoint_id)
                    if last_alert:
                        time_since_last = (datetime.now(timezone(timedelta(hours=5, minutes=30))) - last_alert).total_seconds()
                        remaining_time = 60 - time_since_last
                        logger.info(f"Email alert throttled for {config.name} - next alert in {remaining_time:.0f} seconds")
            
            logger.info(f"Manual test for {config.name}: {'SUCCESS' if is_success else 'FAILED'}")
            
            return {
                "success": True,
                "test_result": {
                    "status_code": status_code,
                    "response_time_ms": response_time_ms,
                    "is_success": is_success,
                    "error_message": error_message,
                    "response_body": response_body,
                    "timestamp": datetime.now(timezone(timedelta(hours=5, minutes=30)))
                }
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error testing heartbeat endpoint: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def check_endpoint(self, config: APIHeartbeatConfig) -> None:
        """Check a single endpoint and store the result"""
        db = SessionLocal()
        try:
            start_time = time.time()
            is_success = False
            status_code = None
            error_message = None
            response_body = None
            
            try:
                # Prepare request
                headers = config.headers or {}
                data = config.body if config.method in ['POST', 'PUT', 'PATCH'] else None
                
                # Add User-Agent if not present
                if 'User-Agent' not in headers:
                    headers['User-Agent'] = 'HeartbeatMonitor/1.0'
                
                response = requests.request(
                    method=config.method,
                    url=config.url,
                    headers=headers,
                    data=data,
                    timeout=config.timeout_seconds,
                    allow_redirects=True
                )
                
                status_code = response.status_code
                response_body = response.text[:1000]  # Limit response body size
                
                # Check if test was successful based on expected status and response
                is_success = (
                    status_code in config.expected_status and
                    (not config.expected_response or config.expected_response in response_body)
                )
                
            except requests.exceptions.Timeout:
                error_message = "Request timeout"
            except requests.exceptions.ConnectionError:
                error_message = "Connection error"
            except Exception as e:
                error_message = str(e)
            
            response_time_ms = (time.time() - start_time) * 1000
            
            # Create IST timestamp
            ist_timezone = timezone(timedelta(hours=5, minutes=30))
            ist_timestamp = datetime.now(ist_timezone)
            
            # Store result
            result = HeartbeatResult(
                config_id=config.id,
                status_code=status_code,
                response_time_ms=response_time_ms,
                is_success=is_success,
                error_message=error_message,
                response_body=response_body,
                timestamp=ist_timestamp
            )
            
            db.add(result)
            db.commit()
            
            # Check if status is not 200 and send email alert (with throttling)
            if status_code != 200:
                logger.warning(f"Status code {status_code} for {config.name}")
                
                # Check if we should send alert (respecting 1-minute gap)
                if self.should_send_alert(config.id):
                    logger.info(f"Sending email alert for {config.name} failure")
                    try:
                        # Send failure alert
                        email_result = self.email_service.send_heartbeat_alert(
                            endpoint_name=config.name,
                            endpoint_url=config.url,
                            method=config.method,
                            status_code=status_code,
                            response_time_ms=response_time_ms,
                            error_message=error_message
                        )
                        
                        if email_result["success"]:
                            self.update_last_alert_time(config.id)
                            logger.info(f"Email alert sent for {config.name} failure")
                        else:
                            logger.error(f"Failed to send email alert for {config.name}: {email_result.get('error', 'Unknown error')}")
                            
                    except Exception as e:
                        logger.error(f"Error sending email alert for {config.name}: {str(e)}")
                else:
                    last_alert = self.last_alert_time.get(config.id)
                    if last_alert:
                        time_since_last = (datetime.now(timezone(timedelta(hours=5, minutes=30))) - last_alert).total_seconds()
                        remaining_time = 60 - time_since_last
                        logger.info(f"Email alert throttled for {config.name} - next alert in {remaining_time:.0f} seconds")
            
            # Check for recovery (status changed from failure to success)
            previous_status = self.previous_status.get(config.id, None)
            if previous_status is False and is_success:
                logger.info(f"Recovery detected for {config.name} - sending recovery notification")
                try:
                    # Send recovery notification (recovery emails are not throttled)
                    email_result = self.email_service.send_heartbeat_alert(
                        endpoint_name=config.name,
                        endpoint_url=config.url,
                        method=config.method,
                        status_code=status_code,
                        response_time_ms=response_time_ms,
                        error_message=error_message,
                        is_recovery=True
                    )
                    
                    if email_result["success"]:
                        logger.info(f"Recovery notification sent for {config.name}")
                    else:
                        logger.error(f"Failed to send recovery notification for {config.name}: {email_result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    logger.error(f"Error sending recovery notification for {config.name}: {str(e)}")
            
            # Update previous status
            self.previous_status[config.id] = is_success
            
            logger.info(f"Heartbeat check for {config.name}: {'SUCCESS' if is_success else 'FAILED'} (Status: {status_code}, Time: {response_time_ms:.2f}ms)")
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error checking endpoint {config.name}: {str(e)}")
        finally:
            db.close()

    def run_monitoring_cycle(self) -> None:
        """Run one cycle of monitoring for all active endpoints"""
        db = SessionLocal()
        try:
            configs = db.query(APIHeartbeatConfig).filter(APIHeartbeatConfig.is_active == True).all()
            
            for config in configs:
                # Check if it's time to monitor this endpoint
                latest_result = db.query(HeartbeatResult).filter(
                    HeartbeatResult.config_id == config.id
                ).order_by(HeartbeatResult.timestamp.desc()).first()
                
                should_check = True
                if latest_result:
                    # IST timezone (UTC+5:30)
                    ist_timezone = timezone(timedelta(hours=5, minutes=30))
                    current_time = datetime.now(ist_timezone)
                    
                    # Handle timezone-aware vs naive timestamps
                    if latest_result.timestamp.tzinfo is None:
                        # If timestamp is naive, assume it's in IST
                        last_check_time = latest_result.timestamp.replace(tzinfo=ist_timezone)
                    else:
                        last_check_time = latest_result.timestamp
                    
                    time_since_last = current_time - last_check_time
                    interval_seconds = config.interval_minutes * 60
                    should_check = time_since_last.total_seconds() >= interval_seconds
                    
                    if not should_check:
                        remaining_seconds = interval_seconds - time_since_last.total_seconds()
                        logger.debug(f"Skipping {config.name} - next check in {remaining_seconds:.0f} seconds")
                
                if should_check:
                    logger.info(f"Running heartbeat check for {config.name} (interval: {config.interval_minutes} minutes)")
                    self.check_endpoint(config)
                else:
                    logger.debug(f"Skipping heartbeat check for {config.name} - not yet due")
                    
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {str(e)}")
        finally:
            db.close()

    def start_monitoring(self) -> None:
        """Start the monitoring service"""
        self.monitoring = True
        logger.info("Starting heartbeat monitoring service")
        
        while self.monitoring:
            try:
                self.run_monitoring_cycle()
                time.sleep(60)  # Check every 60 seconds (more efficient)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")
                time.sleep(60)  # Wait longer on error

    def stop_monitoring(self) -> None:
        """Stop the monitoring service"""
        self.monitoring = False
        logger.info("Stopping heartbeat monitoring service")