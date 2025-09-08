"""
Integrated Monitor - Main Application

A comprehensive monitoring system that provides:
- Heartbeat monitoring for API endpoints
- S3 bucket monitoring and log analysis
- S3 API monitoring through log analysis
- Manual testing capabilities
- Grafana dashboard integration
- Complete REST API with documentation

Author: Integrated Monitor Team
Version: 1.0.0
"""

from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import uvicorn
import threading
import os
import logging
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
import json
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import models and services
from app.db.models import (
    APIHeartbeatConfigCreate, S3BucketConfigCreate, ManualTestConfigCreate,
    ManualTestRequest, S3APIConfigCreate, S3BucketConfig, S3LogEntry,
    UserCreate, UserLogin, UserResponse, RoleCreate, RoleResponse, TokenResponse, User, Role
)
from app.db.session import engine, Base, get_db
from app.services.heartbeat_monitor import HeartbeatMonitor
from app.services.s3_unified_monitor import UnifiedS3Monitor
from app.services.manual_test import ManualTestService
from app.services.email_service import EmailService
from app.services.grafana_service import GrafanaService
from app.services.auth_service import (
    auth_service, get_current_user, require_permission, DEFAULT_ROLES
)
 
# Load environment variables
load_dotenv()

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize services
heartbeat_monitor = HeartbeatMonitor()
unified_s3_monitor = UnifiedS3Monitor()
manual_test_service = ManualTestService()
email_service = EmailService()
grafana_service = GrafanaService()

# IST timezone utility function
def get_ist_timezone():
    """Get IST timezone (UTC+5:30)"""
    return pytz.timezone('Asia/Kolkata')

# Create FastAPI app
app = FastAPI(
    title="Integrated Monitor API",
    description="Comprehensive API monitoring system",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5000", "http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize monitoring services on startup"""
    try:
        logger.info("Starting Integrated Monitor Dashboard...")
        
        # Start heartbeat monitoring in background
        logger.info("Starting heartbeat monitoring...")
        heartbeat_thread = threading.Thread(target=heartbeat_monitor.start_monitoring, daemon=True)
        heartbeat_thread.start()
        logger.info(f"Heartbeat monitoring started (Thread ID: {heartbeat_thread.ident})")
        
        # Start unified S3 monitoring in background
        logger.info("Starting unified S3 monitoring...")
        s3_thread = threading.Thread(target=unified_s3_monitor.start_monitoring, daemon=True)
        s3_thread.start()
        logger.info(f"Unified S3 monitoring started (Thread ID: {s3_thread.ident})")
        
        logger.info("All monitoring services started successfully!")
        
    except Exception as e:
        logger.error(f"Error starting monitoring services: {e}")
        raise

# ============================================================================
# AUTHENTICATION APIs
# ============================================================================

@app.post("/api/auth/login", response_model=TokenResponse)
async def login(user_credentials: UserLogin, db: Session = Depends(get_db)):
    """User login endpoint"""
    try:
        # Authenticate user
        user = auth_service.authenticate_user(db, user_credentials.username, user_credentials.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password"
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user account"
            )
        
        # Update last login
        auth_service.update_last_login(db, user.id)
        
        # Get user roles
        roles = auth_service.get_user_roles(db, user.id)
        
        # Create access token
        access_token_expires = timedelta(minutes=auth_service.access_token_expire_minutes)
        access_token = auth_service.create_access_token(
            data={"sub": user.username}, expires_delta=access_token_expires
        )
        
        # Prepare user response
        user_response = UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            is_verified=user.is_verified,
            last_login=user.last_login,
            created_at=user.created_at,
            roles=roles
        )
        
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=auth_service.access_token_expire_minutes * 60,
            user=user_response
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@app.post("/api/auth/register", response_model=UserResponse)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """User registration endpoint"""
    try:
        user = auth_service.create_user(db, user_data)
        
        # Get user roles
        roles = auth_service.get_user_roles(db, user.id)
        
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            is_verified=user.is_verified,
            last_login=user.last_login,
            created_at=user.created_at,
            roles=roles
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@app.post("/api/auth/register-admin", response_model=UserResponse)
async def register_admin(
    user_data: UserCreate, 
    current_user: User = Depends(require_permission("users", "write")),
    db: Session = Depends(get_db)
):
    """Admin user registration endpoint (admin only)"""
    try:
        # Only admins can register new users
        if not auth_service.has_role(db, current_user, "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can register new users"
            )
        
        user = auth_service.create_user(db, user_data)
        
        # Get user roles
        roles = auth_service.get_user_roles(db, user.id)
        
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            is_verified=user.is_verified,
            last_login=user.last_login,
            created_at=user.created_at,
            roles=roles
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin registration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@app.get("/api/auth/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current user information"""
    try:
        roles = auth_service.get_user_roles(db, current_user.id)
        
        return UserResponse(
            id=current_user.id,
            username=current_user.username,
            email=current_user.email,
            first_name=current_user.first_name,
            last_name=current_user.last_name,
            is_active=current_user.is_active,
            is_verified=current_user.is_verified,
            last_login=current_user.last_login,
            created_at=current_user.created_at,
            roles=roles
        )
        
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@app.post("/api/auth/init-roles")
async def initialize_default_roles(db: Session = Depends(get_db)):
    """Initialize default roles in the system"""
    try:
        created_roles = []
        
        for role_name, role_data in DEFAULT_ROLES.items():
            # Check if role already exists
            existing_role = db.query(Role).filter(Role.name == role_name).first()
            if not existing_role:
                role = Role(
                    name=role_name,
                    description=role_data["description"],
                    permissions=role_data["permissions"]
                )
                db.add(role)
                created_roles.append(role_name)
        
        if created_roles:
            db.commit()
            return {"message": f"Created roles: {', '.join(created_roles)}"}
        else:
            return {"message": "All default roles already exist"}
            
    except Exception as e:
        logger.error(f"Error initializing roles: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@app.put("/api/auth/users/{username}/role")
async def update_user_role(
    username: str, 
    role_name: str, 
    current_user: User = Depends(require_permission("roles", "write")),
    db: Session = Depends(get_db)
):
    """Update user's role (admin only)"""
    try:
        # Only admins can change user roles
        if not auth_service.has_role(db, current_user, "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can change user roles"
            )
        
        success = auth_service.update_user_role(db, username, role_name)
        if success:
            return {"message": f"Updated role for user {username} to {role_name}"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user role"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user role: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

# ============================================================================
# ADMIN USER MANAGEMENT ENDPOINTS
# ============================================================================

@app.get("/api/admin/users")
async def get_users(
    current_user: User = Depends(require_permission("users", "read")),
    db: Session = Depends(get_db)
):
    """Get all users (admin only)"""
    try:
        users = auth_service.get_all_users(db)
        return {"success": True, "users": users}
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@app.post("/api/admin/users")
async def create_user_by_admin(
    user_data: UserCreate,
    role_name: str = "viewer",
    current_user: User = Depends(require_permission("users", "write")),
    db: Session = Depends(get_db)
):
    """Create a new user (admin only)"""
    try:
        # Create user using auth service
        user = auth_service.create_user(db, user_data)
        
        # If a specific role is requested and it's not the default, assign it
        if role_name != "viewer":
            success = auth_service.assign_role_to_user(db, user.username, role_name)
            if not success:
                logger.warning(f"Failed to assign role {role_name} to user {user.username}")
        
        # Get user roles for response
        roles = auth_service.get_user_roles(db, user.id)
        
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            is_verified=user.is_verified,
            last_login=user.last_login,
            created_at=user.created_at,
            roles=roles
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@app.get("/api/admin/roles")
async def get_roles(
    current_user: User = Depends(require_permission("roles", "read")),
    db: Session = Depends(get_db)
):
    """Get all roles (admin only)"""
    try:
        roles = auth_service.get_all_roles(db)
        return {"success": True, "roles": roles}
    except Exception as e:
        logger.error(f"Error getting roles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@app.delete("/api/admin/users/{username}")
async def delete_user(
    username: str, 
    current_user: User = Depends(require_permission("users", "delete")),
    db: Session = Depends(get_db)
):
    """Delete a user (admin only)"""
    try:
        # Prevent deletion of admin user
        if username == "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete admin user"
            )
        
        # Prevent self-deletion
        if username == current_user.username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete yourself"
            )
        
        success = auth_service.delete_user(db, username)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return {"success": True, "message": f"User {username} deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@app.put("/api/admin/users/{username}/permissions")
async def update_user_permissions(
    username: str,
    permissions: dict,
    current_user: User = Depends(require_permission("users", "write")),
    db: Session = Depends(get_db)
):
    """Update user permissions (admin only)"""
    try:
        success = auth_service.update_user_permissions(db, username, permissions)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return {"success": True, "message": f"Permissions updated for user {username}"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

# ============================================================================
# HEARTBEAT MONITORING APIs - Complete CRUD Operations
# ============================================================================

@app.post("/api/heartbeat/add")
async def add_heartbeat_endpoint(
    api_config: APIHeartbeatConfigCreate,
    current_user: User = Depends(require_permission("api_management", "write"))
):
    """Add a new API endpoint for heartbeat monitoring (admin only)"""
    return await heartbeat_monitor.add_endpoint(api_config)

@app.get("/api/heartbeat/endpoints")
async def get_all_heartbeat_endpoints():
    """Get all heartbeat monitoring endpoints"""
    return await heartbeat_monitor.get_all_endpoints()

@app.get("/api/heartbeat/endpoints/{endpoint_id}")
async def get_heartbeat_endpoint(endpoint_id: int):
    """Get a specific heartbeat endpoint by ID"""
    return await heartbeat_monitor.get_endpoint(endpoint_id)

@app.put("/api/heartbeat/update/{endpoint_id}")
async def update_heartbeat_endpoint(
    endpoint_id: int, 
    api_config: APIHeartbeatConfigCreate,
    current_user: User = Depends(require_permission("api_management", "write"))
):
    """Update an existing API endpoint for heartbeat monitoring (admin only)"""
    return await heartbeat_monitor.update_endpoint(endpoint_id, api_config)

@app.delete("/api/heartbeat/delete/{endpoint_id}")
async def delete_heartbeat_endpoint(
    endpoint_id: int,
    current_user: User = Depends(require_permission("api_management", "delete"))
):
    """Delete a heartbeat monitoring endpoint (admin only)"""
    return await heartbeat_monitor.delete_endpoint(endpoint_id)

@app.get("/api/heartbeat/status")
async def get_heartbeat_status():
    """Get status of all heartbeat monitored endpoints"""
    return await heartbeat_monitor.get_status()

@app.get("/api/heartbeat/history/{endpoint_id}")
async def get_heartbeat_history(endpoint_id: int, hours: int = 24):
    """Get heartbeat history for a specific endpoint"""
    return await heartbeat_monitor.get_history(endpoint_id, hours)

@app.post("/api/heartbeat/test/{endpoint_id}")
async def test_heartbeat_endpoint(endpoint_id: int):
    """Manually test a heartbeat endpoint"""
    return await heartbeat_monitor.test_endpoint(endpoint_id)

# ============================================================================
# S3 MONITORING APIs - Complete CRUD Operations
# ============================================================================

@app.post("/api/s3/add")
async def add_s3_bucket(
    api_config: S3BucketConfigCreate,
    current_user: User = Depends(require_permission("api_management", "write"))
):
    """Add a new S3 bucket for monitoring (admin only)"""
    return await unified_s3_monitor.add_bucket(api_config)

@app.get("/api/s3/buckets")
async def get_all_s3_buckets():
    """Get all S3 bucket configurations"""
    return await unified_s3_monitor.get_all_buckets()

@app.get("/api/s3/buckets/status")
async def get_s3_bucket_statuses():
    """Get S3 bucket statuses with monitoring information"""
    return await unified_s3_monitor.get_bucket_statuses()

@app.get("/api/s3/buckets/{bucket_id}")
async def get_s3_bucket(bucket_id: int):
    """Get a specific S3 bucket configuration by ID"""
    return await unified_s3_monitor.get_bucket(bucket_id)

@app.put("/api/s3/update/{bucket_id}")
async def update_s3_bucket(
    bucket_id: int, 
    api_config: S3BucketConfigCreate,
    current_user: User = Depends(require_permission("api_management", "write"))
):
    """Update an existing S3 bucket configuration (admin only)"""
    return await unified_s3_monitor.update_bucket(bucket_id, api_config)

@app.delete("/api/s3/delete/{bucket_id}")
async def delete_s3_bucket(
    bucket_id: int,
    current_user: User = Depends(require_permission("api_management", "delete"))
):
    """Delete an S3 bucket configuration (admin only)"""
    return await unified_s3_monitor.delete_bucket(bucket_id)

@app.get("/api/s3/status")
async def get_s3_status():
    """Get status of all S3 bucket monitoring"""
    return await unified_s3_monitor.get_status()

@app.get("/api/s3/logs/{bucket_id}")
async def get_s3_logs(bucket_id: int, hours: int = 24):
    """Get S3 bucket logs for a specific bucket"""
    try:
        # Get bucket details to resolve bucket_name
        bucket_resp = await unified_s3_monitor.get_bucket(bucket_id)
        if not bucket_resp.get("success"):
            return {"success": False, "error": "Bucket not found"}

        bucket = bucket_resp.get("bucket", {})
        bucket_name = bucket.get("bucket_name")
        if not bucket_name:
            return {"success": False, "error": "Bucket name not found"}

        # Return S3 API logs (S3APILog) for this bucket to match UI expectations
        logs_resp = await unified_s3_monitor.get_logs_from_db(
            api_id=None,
            bucket_name=bucket_name,
            hours=hours,
            limit=100
        )
        
        # Add debug info for troubleshooting
        logger.info(f"S3 Logs for bucket {bucket_name}: {logs_resp}")
        
        return logs_resp

    except Exception as e:
        logger.error(f"Error getting S3 logs for bucket {bucket_id}: {str(e)}")
        return {"success": False, "error": str(e)}

@app.get("/api/s3/logs/{bucket_id}/content")
async def get_s3_logs_with_content(bucket_id: int, hours: int = 24, limit: int = 50):
    """Get S3 bucket logs with content and URLs"""
    return await unified_s3_monitor.get_bucket_logs_with_content(bucket_id, hours, limit)

@app.get("/api/s3/bucket/{bucket_id}/urls")
async def get_s3_bucket_urls(bucket_id: int):
    """Get S3 bucket URLs and access information"""
    return await unified_s3_monitor.get_bucket_urls(bucket_id)

@app.get("/api/s3/logs/content/{log_id}")
async def get_s3_log_content(log_id: int):
    """Get full log content for a specific log entry"""
    return await unified_s3_monitor.get_log_content(log_id)

@app.post("/api/s3/refresh/{bucket_id}")
async def refresh_s3_bucket(bucket_id: int):
    """Manually refresh S3 bucket logs"""
    return await unified_s3_monitor.refresh_bucket_logs(bucket_id)

@app.post("/api/s3/api/refresh-logs/{bucket_id}")
async def refresh_s3_api_logs(bucket_id: int):
    """Manually refresh S3 API logs for a specific bucket"""
    try:
        # Get the bucket configuration
        bucket_config = await unified_s3_monitor.get_bucket(bucket_id)
        if not bucket_config.get("success"):
            return {"success": False, "error": "Bucket not found"}
        
        from app.db.session import SessionLocal
        
        db = SessionLocal()
        try:
            config = db.query(S3BucketConfig).filter(S3BucketConfig.id == bucket_id).first()
            if not config:
                return {"success": False, "error": "Bucket configuration not found"}
            
            # Refresh logs using the S3 monitor
            unified_s3_monitor.check_bucket_logs(config)
            
            return {"success": True, "message": f"Successfully refreshed S3 API logs for bucket {config.bucket_name}"}
            
        finally:
            db.close()
            
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/s3/default-config")
async def get_s3_default_config():
    """Get default S3 configuration from environment variables"""
    return unified_s3_monitor.get_default_s3_config()

@app.post("/api/s3/process-logs/{bucket_id}")
async def process_s3_logs(bucket_id: int, log_key: str):
    """Download and process S3 log file with enhanced parsing"""
    try:
        # Get the bucket configuration
        bucket_config = await unified_s3_monitor.get_bucket(bucket_id)
        if not bucket_config.get("success"):
            return {"success": False, "error": "Bucket not found"}
        
        bucket_name = bucket_config.get("bucket", {}).get("bucket_name")
        if not bucket_name:
            return {"success": False, "error": "Bucket name not found"}
        
        # Process the log file
        result = await unified_s3_monitor.download_and_process_s3_logs(bucket_name, log_key)
        return result
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/s3/process-logs/batch/{bucket_id}")
async def process_s3_logs_batch(bucket_id: int, log_keys: List[str]):
    """Process multiple S3 log files in batch"""
    try:
        # Get the bucket configuration
        bucket_config = await unified_s3_monitor.get_bucket(bucket_id)
        if not bucket_config.get("success"):
            return {"success": False, "error": "Bucket not found"}
        
        bucket_name = bucket_config.get("bucket", {}).get("bucket_name")
        if not bucket_name:
            return {"success": False, "error": "Bucket name not found"}
        
        # Process each log file
        results = []
        for log_key in log_keys:
            result = await unified_s3_monitor.download_and_process_s3_logs(bucket_name, log_key)
            results.append(result)
        
        return {
            "success": True,
            "results": results,
            "total_files": len(log_keys),
            "bucket_name": bucket_name
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# MANUAL TEST APIs - Complete CRUD Operations
# ============================================================================

@app.post("/api/manual/endpoints")
async def add_manual_endpoint(api_config: ManualTestConfigCreate):
    """Add a new endpoint for manual testing"""
    return await manual_test_service.add_endpoint(api_config)

@app.get("/api/manual/endpoints")
async def get_all_manual_endpoints():
    """Get all configured endpoints for manual testing"""
    return await manual_test_service.get_all_endpoints()

@app.get("/api/manual/endpoints/{endpoint_id}")
async def get_manual_endpoint(endpoint_id: int):
    """Get a specific manual test endpoint by ID"""
    return await manual_test_service.get_endpoint(endpoint_id)

@app.put("/api/manual/update/{endpoint_id}")
async def update_manual_endpoint(endpoint_id: int, api_config: ManualTestConfigCreate):
    """Update an existing manual test endpoint"""
    return await manual_test_service.update_endpoint(endpoint_id, api_config)

@app.delete("/api/manual/endpoints/{endpoint_id}")
async def delete_manual_endpoint(endpoint_id: int):
    """Delete a manual test endpoint"""
    return await manual_test_service.delete_endpoint(endpoint_id)

@app.post("/api/manual/test")
async def test_manual_endpoint(test_request: ManualTestRequest):
    """Manually test an endpoint"""
    return await manual_test_service.test_endpoint(test_request)

@app.get("/api/manual/results")
async def get_manual_test_results(hours: int = 24):
    """Get manual test results"""
    return await manual_test_service.get_results(hours)

@app.get("/api/manual/results/{endpoint_id}")
async def get_manual_test_results_by_endpoint(endpoint_id: int, hours: int = 24):
    """Get manual test results for a specific endpoint"""
    return await manual_test_service.get_results_by_endpoint(endpoint_id, hours)

# ============================================================================
# S3 API MONITORING APIs - Complete CRUD Operations
# ============================================================================

@app.post("/api/s3/api/add")
async def add_s3_api_config(api_config: S3APIConfigCreate):
    """Add a new API configuration for S3 monitoring"""
    config_dict = {
        'name': api_config.name,
        'url': api_config.url,
        'method': api_config.method,
        'expected_status': api_config.expected_status,
        'headers': api_config.headers,
        'body': api_config.body,
        'expected_response': api_config.expected_response,
        'bucket_id': api_config.bucket_id
    }
    return await unified_s3_monitor.add_api_config(config_dict)

@app.get("/api/s3/api/configs")
async def get_all_s3_api_configs():
    """Get all S3 API configurations"""
    return await unified_s3_monitor.get_api_configs()

@app.get("/api/s3/api/configs/{config_id}")
async def get_s3_api_config(config_id: int):
    """Get a specific S3 API configuration by ID"""
    return await unified_s3_monitor.get_api_config(config_id)

@app.put("/api/s3/api/update/{config_id}")
async def update_s3_api_config(config_id: int, api_config: S3APIConfigCreate):
    """Update an existing S3 API configuration"""
    config_dict = {
        'name': api_config.name,
        'url': api_config.url,
        'method': api_config.method,
        'expected_status': api_config.expected_status,
        'headers': api_config.headers,
        'body': api_config.body,
        'expected_response': api_config.expected_response,
        'bucket_id': api_config.bucket_id
    }
    return await unified_s3_monitor.update_api_config(config_id, config_dict)

@app.delete("/api/s3/api/delete/{config_id}")
async def delete_s3_api_config(config_id: int):
    """Delete an S3 API configuration"""
    return await unified_s3_monitor.delete_api_config(config_id)

@app.get("/api/s3/api/status")
async def get_s3_api_status():
    """Get status of all APIs monitored from S3 logs"""
    return await unified_s3_monitor.get_api_status()

@app.get("/api/s3/api/log-analysis/{api_id}")
async def get_s3_api_log_analysis(api_id: int, hours: int = 24):
    """Get detailed S3 log analysis for a specific API"""
    return await unified_s3_monitor.get_log_analysis(api_id, hours)

@app.get("/api/s3/api/logs")
async def get_s3_api_logs(api_id: Optional[int] = None, bucket_name: Optional[str] = None, 
                         hours: int = 24, limit: Optional[int] = None):
    """Get S3 API logs from database"""
    return await unified_s3_monitor.get_logs_from_db(api_id, bucket_name, hours, limit)

@app.get("/api/s3/api/latest-logs")
async def get_latest_s3_api_logs(hours: int = 24, limit: Optional[int] = None):
    """Get the latest S3 API logs from bucket monitoring"""
    return await unified_s3_monitor.get_latest_api_logs(hours, limit)

@app.get("/api/s3/api/logs/realtime")
async def get_realtime_s3_api_logs(api_name: Optional[str] = None, minutes: int = 5):
    """Get real-time S3 API logs (last few minutes) for live monitoring"""
    try:
        # Get logs from the last few minutes for real-time display
        from datetime import datetime, timedelta, timezone
        
        # IST timezone (UTC+5:30)
        ist_timezone = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(ist_timezone)
        start_time = now - timedelta(minutes=minutes)
        
        # Convert to string format for database query
        start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Get real-time logs
        realtime_logs = await unified_s3_monitor.get_realtime_logs(api_name, start_time_str, minutes)
        
        return {
            "success": True,
            "data": realtime_logs,
            "query_time": now.isoformat(),
            "time_range": f"Last {minutes} minutes",
            "total_logs": len(realtime_logs) if isinstance(realtime_logs, list) else 0
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/s3/api/logs/stream")
async def stream_s3_api_logs(api_name: Optional[str] = None):
    """Stream S3 API logs in real-time using Server-Sent Events"""
    
    async def log_stream():
        """Stream logs in real-time"""
        try:
            while True:
                # Get latest logs every 10 seconds
                logs = await unified_s3_monitor.get_realtime_logs(api_name, None, 2)
                
                # Format as Server-Sent Event
                data = {
                    "timestamp": datetime.now(get_ist_timezone()).isoformat(),
                    "logs": logs,
                    "count": len(logs) if isinstance(logs, list) else 0
                }
                
                yield f"data: {json.dumps(data)}\n\n"
                
                # Wait 10 seconds before next update
                await asyncio.sleep(10)
                
        except asyncio.CancelledError:
            # Client disconnected
            pass
        except Exception as e:
            error_data = {"error": str(e), "timestamp": datetime.now(get_ist_timezone()).isoformat()}
            yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(
        log_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream"
        }
    )

@app.get("/api/s3/api/logs/{log_id}")
async def get_s3_api_log_detail(log_id: int):
    """Get detailed information about a specific S3 API log entry"""
    return await unified_s3_monitor.get_log_detail(log_id)

@app.get("/api/s3/api/summary")
async def get_s3_api_summary():
    """Get summary of S3 API monitoring"""
    status = await unified_s3_monitor.get_api_status()
    return status.get('status_summary', {})

# ============================================================================
# GRAFANA INTEGRATION APIs
# ============================================================================

@app.post("/api/grafana/setup")
async def setup_grafana_dashboard():
    """Setup Grafana dashboard and datasource"""
    return await grafana_service.setup_dashboard()

@app.get("/api/grafana/status")
async def get_grafana_status():
    """Get Grafana connection status"""
    return await grafana_service.get_status()

# ============================================================================
# EMAIL SERVICE APIs
# ============================================================================

@app.get("/api/email/status")
async def get_email_status():
    """Get email service configuration status"""
    return await email_service.get_configuration_status()

@app.post("/api/email/test")
async def test_email_configuration():
    """Test email configuration by sending a test email"""
    return await email_service.test_email_configuration()

# ============================================================================
# GENERAL UTILITY APIs
# ============================================================================

@app.get("/api/stats")
async def get_system_stats():
    """Get overall system statistics"""
    try:
        # Get counts from all services
        heartbeat_status = await heartbeat_monitor.get_status()
        s3_status = await unified_s3_monitor.get_status()
        manual_endpoints = await manual_test_service.get_all_endpoints()
        s3_api_configs = await unified_s3_monitor.get_api_configs()
        
        stats = {
            "heartbeat_endpoints": len(heartbeat_status),
            "s3_buckets": s3_status.get("active_buckets", 0) if isinstance(s3_status, dict) else 0,
            "manual_endpoints": len(manual_endpoints),
            "s3_api_configs": len(s3_api_configs),
            "total_endpoints": len(heartbeat_status) + len(manual_endpoints) + len(s3_api_configs),
            "timestamp": datetime.now(get_ist_timezone()).isoformat()
        }
        
        return {"success": True, "stats": stats}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/refresh/all")
async def refresh_all_data():
    """Trigger refresh of all monitoring data"""
    try:
        # This would trigger background refresh of all monitoring services
        # For now, just return success
        return {"success": True, "message": "Refresh triggered for all monitoring services"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/s3/start-monitoring")
async def start_s3_monitoring():
    """Manually start S3 monitoring services"""
    try:
        logger.info("Manually starting S3 monitoring services...")
        
        # Start S3 monitoring in background
        s3_thread = threading.Thread(target=unified_s3_monitor.start_monitoring, daemon=True)
        s3_thread.start()
        
        # Start S3 API monitoring in background
        s3_api_thread = threading.Thread(target=unified_s3_monitor.start_monitoring, daemon=True)
        s3_api_thread.start()
        
        logger.info("S3 monitoring services started manually")
        
        return {
            "success": True, 
            "message": "S3 monitoring services started successfully",
            "s3_thread_id": s3_thread.ident,
            "s3_api_thread_id": s3_api_thread.ident
        }
        
    except Exception as e:
        logger.error(f"Error starting S3 monitoring: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/s3/monitoring-status")
async def get_s3_monitoring_status():
    """Get the status of S3 monitoring services"""
    try:
        # Check if monitoring threads are alive
        import threading
        
        # Get all active threads
        active_threads = threading.enumerate()
        
        # Check for our monitoring threads (this is a basic check)
        monitoring_status = {
            "s3_monitor_running": hasattr(unified_s3_monitor, 'monitoring') and unified_s3_monitor.monitoring,
            "s3_api_monitor_running": hasattr(unified_s3_monitor, 'monitoring') and unified_s3_monitor.monitoring,
            "active_threads_count": len(active_threads),
            "daemon_threads_count": len([t for t in active_threads if t.daemon]),
            "timestamp": datetime.now(get_ist_timezone()).isoformat()
        }
        
        return {"success": True, "status": monitoring_status}
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/s3/cleanup-status")
async def get_s3_cleanup_status():
    """Get S3 local log cleanup status"""
    try:
        cleanup_status = unified_s3_monitor.get_cleanup_status()
        return {"success": True, "cleanup_status": cleanup_status}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# DEFERRED LOG PROCESSING APIs
# ============================================================================

@app.post("/api/s3/process-stored-log/{log_id}")
async def process_stored_log(log_id: int):
    """Process a specific stored log for API analysis"""
    try:
        result = await unified_s3_monitor.process_stored_log_content(log_id)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/s3/process-all-stored-logs")
async def process_all_stored_logs(limit: int = 100):
    """Process all stored logs for API analysis in batch"""
    try:
        result = await unified_s3_monitor.process_all_stored_logs(limit)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/s3/stored-logs-status")
async def get_stored_logs_status():
    """Get status of stored logs and their processing state"""
    try:
        db = next(get_db())
        
        # Get counts of logs by processing status
        total_logs = db.query(S3LogEntry).count()
        processed_logs = db.query(S3LogEntry).filter(
            S3LogEntry.parsed_data.op('->>')('api_processing') == 'completed'
        ).count()
        pending_logs = db.query(S3LogEntry).filter(
            S3LogEntry.parsed_data.op('->>')('api_processing') == 'deferred'
        ).count()
        failed_logs = db.query(S3LogEntry).filter(
            S3LogEntry.parsed_data.op('->>')('api_processing') == 'failed'
        ).count()
        
        status = {
            "total_logs": total_logs,
            "processed_logs": processed_logs,
            "pending_logs": pending_logs,
            "failed_logs": failed_logs,
            "timestamp": datetime.now(get_ist_timezone()).isoformat()
        }
        
        return {"success": True, "status": status}
        
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# DEBUG AND TESTING ENDPOINTS
# ============================================================================

@app.get("/api/debug/s3-logs-count")
async def debug_s3_logs_count():
    """Debug endpoint to check S3 logs count"""
    try:
        from app.db.session import SessionLocal
        from app.db.models import S3APILog, S3BucketConfig
        
        db = SessionLocal()
        try:
            # Count total S3 API logs
            total_logs = db.query(S3APILog).count()
            
            # Count S3 buckets
            total_buckets = db.query(S3BucketConfig).count()
            
            # Get sample logs
            sample_logs = db.query(S3APILog).limit(5).all()
            
            # Get all bucket names with logs
            bucket_logs_count = db.query(S3APILog.bucket_name, db.func.count(S3APILog.id)).group_by(S3APILog.bucket_name).all()
            
            return {
                "success": True,
                "total_s3_api_logs": total_logs,
                "total_s3_buckets": total_buckets,
                "bucket_logs_count": [{"bucket_name": name, "count": count} for name, count in bucket_logs_count],
                "sample_logs": [
                    {
                        "id": log.id,
                        "api_url": log.api_url,
                        "bucket_name": log.bucket_name,
                        "timestamp": log.timestamp.isoformat() if log.timestamp else None
                    } for log in sample_logs
                ]
            }
        finally:
            db.close()
            
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/debug/create-sample-s3-logs/{bucket_id}")
async def create_sample_s3_logs(bucket_id: int):
    """Create sample S3 API logs for testing"""
    try:
        from app.db.session import SessionLocal
        from app.db.models import S3APILog, S3BucketConfig
        from datetime import datetime, timezone, timedelta
        
        db = SessionLocal()
        try:
            # Get bucket details
            bucket = db.query(S3BucketConfig).filter(S3BucketConfig.id == bucket_id).first()
            if not bucket:
                return {"success": False, "error": "Bucket not found"}
            
            # Create sample logs
            sample_logs = []
            for i in range(5):
                log = S3APILog(
                    api_url=f"https://api.example.com/test/{i+1}",
                    timestamp=datetime.now(timezone(timedelta(hours=5, minutes=30))) - timedelta(hours=i),
                    request_processing_time=0.1 + (i * 0.05),
                    target_processing_time=0.2 + (i * 0.1),
                    response_processing_time=0.05 + (i * 0.02),
                    elb_status_code=200,
                    target_status_code=200,
                    bucket_name=bucket.bucket_name,
                    api_config_id=None,
                    request_path=f"/test/{i+1}",
                    user_agent="TestAgent/1.0",
                    client_ip=f"192.168.1.{100+i}"
                )
                db.add(log)
                sample_logs.append(log)
            
            db.commit()
            
            return {
                "success": True,
                "message": f"Created {len(sample_logs)} sample logs for bucket {bucket.bucket_name}",
                "bucket_id": bucket_id,
                "bucket_name": bucket.bucket_name
            }
            
        finally:
            db.close()
            
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now(get_ist_timezone())}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)