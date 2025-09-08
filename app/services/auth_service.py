"""
Authentication Service for Integrated Monitor

This service provides user authentication, JWT token management,
and role-based access control functionality.

Author: Integrated Monitor Team
Version: 1.0.0
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.db.models import User, Role, UserRole, UserCreate, UserLogin
from app.db.session import get_db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Security configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT token scheme
security = HTTPBearer()

class AuthService:
    """Authentication service for user management and JWT tokens"""
    
    def __init__(self):
        self.secret_key = SECRET_KEY
        self.algorithm = ALGORITHM
        self.access_token_expire_minutes = ACCESS_TOKEN_EXPIRE_MINUTES
    
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None):
        """Create JWT access token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=self.access_token_expire_minutes)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify JWT token and return payload"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    def authenticate_user(self, db: Session, username: str, password: str) -> Optional[User]:
        """Authenticate user with username and password"""
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                return None
            if not user.check_password(password):
                return None
            return user
        except Exception as e:
            logger.error(f"Error authenticating user {username}: {e}")
            return None
    
    def create_user(self, db: Session, user_data: UserCreate) -> User:
        """Create a new user"""
        try:
            # Check if username or email already exists
            existing_user = db.query(User).filter(
                (User.username == user_data.username) | (User.email == user_data.email)
            ).first()
            
            if existing_user:
                if existing_user.username == user_data.username:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Username already registered"
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email already registered"
                    )
            
            # Create new user
            user = User(
                username=user_data.username,
                email=user_data.email,
                first_name=user_data.first_name,
                last_name=user_data.last_name
            )
            user.set_password(user_data.password)
            
            db.add(user)
            db.commit()
            db.refresh(user)
            
            # Assign role based on username or default to viewer
            if user_data.username.lower() == 'admin':
                self.assign_admin_role(db, user.id)
            else:
                self.assign_default_role(db, user.id)
            
            logger.info(f"User {user.username} created successfully")
            return user
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error"
            )
    
    def assign_default_role(self, db: Session, user_id: int):
        """Assign default viewer role to new user"""
        try:
            # Get or create viewer role
            viewer_role = db.query(Role).filter(Role.name == "viewer").first()
            if not viewer_role:
                viewer_role = Role(
                    name="viewer",
                    description="Basic viewer with read-only access",
                    permissions={
                        "heartbeat": ["read"],
                        "s3": ["read"],
                        "manual_test": ["read"],
                        "system": ["read"],
                        "grafana": ["read"]
                    }
                )
                db.add(viewer_role)
                db.commit()
                db.refresh(viewer_role)
            
            # Assign role to user
            user_role = UserRole(user_id=user_id, role_id=viewer_role.id)
            db.add(user_role)
            db.commit()
            
        except Exception as e:
            logger.error(f"Error assigning default role: {e}")
            db.rollback()
    
    def assign_admin_role(self, db: Session, user_id: int):
        """Assign admin role to user"""
        try:
            # Get or create admin role
            admin_role = db.query(Role).filter(Role.name == "admin").first()
            if not admin_role:
                admin_role = Role(
                    name="admin",
                    description="Full system administrator",
                    permissions={
                        "heartbeat": ["read", "write", "delete"],
                        "s3": ["read", "write", "delete"],
                        "manual_test": ["read", "write", "delete"],
                        "system": ["read", "write", "delete"],
                        "grafana": ["read", "write", "delete"],
                        "users": ["read", "write", "delete"],
                        "roles": ["read", "write", "delete"]
                    }
                )
                db.add(admin_role)
                db.commit()
                db.refresh(admin_role)
            
            # Assign role to user
            user_role = UserRole(user_id=user_id, role_id=admin_role.id)
            db.add(user_role)
            db.commit()
            
        except Exception as e:
            logger.error(f"Error assigning admin role: {e}")
            db.rollback()
    
    def get_user_roles(self, db: Session, user_id: int) -> List[str]:
        """Get list of role names for a user by user_id"""
        try:
            user_roles = db.query(UserRole).filter(UserRole.user_id == user_id).all()
            roles = []
            for user_role in user_roles:
                role = db.query(Role).filter(Role.id == user_role.role_id).first()
                if role:
                    roles.append(role.name)
            return roles
        except Exception as e:
            logger.error(f"Error getting user roles: {e}")
            return []
    
    def get_user_roles_by_username(self, db: Session, username: str) -> List[str]:
        """Get list of role names for a user by username"""
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                return []
            return self.get_user_roles(db, user.id)
        except Exception as e:
            logger.error(f"Error getting user roles: {e}")
            return []
    
    def get_user_permissions(self, db: Session, user_id: int) -> Dict[str, List[str]]:
        """Get permissions for a user by user_id"""
        try:
            user_roles = db.query(UserRole).filter(UserRole.user_id == user_id).all()
            permissions = {}
            
            for user_role in user_roles:
                role = db.query(Role).filter(Role.id == user_role.role_id).first()
                if role and role.permissions:
                    for resource, actions in role.permissions.items():
                        if resource not in permissions:
                            permissions[resource] = []
                        
                        if isinstance(actions, list):
                            # Extend the list, avoiding duplicates
                            for action in actions:
                                if action not in permissions[resource]:
                                    permissions[resource].append(action)
                        else:
                            # Handle case where actions might be a string
                            if actions and actions not in permissions[resource]:
                                permissions[resource].append(actions)
            
            return permissions
        except Exception as e:
            logger.error(f"Error getting user permissions: {e}")
            return {}
    
    def get_user_permissions_by_username(self, db: Session, username: str) -> List[Dict[str, Any]]:
        """Get list of permissions for a user by username (for backward compatibility)"""
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                return []
            
            permissions_dict = self.get_user_permissions(db, user.id)
            permissions_list = []
            
            for resource, actions in permissions_dict.items():
                permissions_list.append({
                    "resource": resource,
                    "actions": actions
                })
            
            return permissions_list
        except Exception as e:
            logger.error(f"Error getting user permissions: {e}")
            return []
    
    def has_permission(self, db: Session, user_id: int, resource: str, action: str) -> bool:
        """Check if user has specific permission"""
        try:
            permissions = self.get_user_permissions(db, user_id)
            if resource in permissions:
                return action in permissions[resource]
            return False
        except Exception as e:
            logger.error(f"Error checking permission: {e}")
            return False
    
    def has_role(self, db: Session, user: User, role_name: str) -> bool:
        """Check if user has specific role"""
        try:
            user_roles = db.query(UserRole).filter(UserRole.user_id == user.id).all()
            for user_role in user_roles:
                role = db.query(Role).filter(Role.id == user_role.role_id).first()
                if role and role.name == role_name:
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking user role: {e}")
            return False
    
    def update_last_login(self, db: Session, user_id: int):
        """Update user's last login timestamp"""
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.last_login = datetime.now(timezone.utc)
                db.commit()
        except Exception as e:
            logger.error(f"Error updating last login: {e}")

    def update_user_role(self, db: Session, username: str, role_name: str):
        """Update user's role"""
        try:
            # Get user
            user = db.query(User).filter(User.username == username).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            # Get role
            role = db.query(Role).filter(Role.name == role_name).first()
            if not role:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Role not found"
                )
            
            # Remove existing role assignments
            db.query(UserRole).filter(UserRole.user_id == user.id).delete()
            
            # Assign new role
            user_role = UserRole(user_id=user.id, role_id=role.id)
            db.add(user_role)
            db.commit()
            
            logger.info(f"Updated role for user {username} to {role_name}")
            return True
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating user role: {e}")
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error"
            )

    def get_all_users(self, db: Session) -> List[Dict[str, Any]]:
        """Get all users with their roles and permissions"""
        try:
            users = db.query(User).all()
            result = []
            for user in users:
                # Get user roles as strings
                user_roles = self.get_user_roles(db, user.id)
                role_names = [role.name for role in user_roles]
                
                # Get user permissions
                user_permissions = self.get_user_permissions_by_username(db, user.username)
                
                # Create a dict representation that matches frontend expectations
                user_dict = {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "is_active": user.is_active,
                    "is_verified": user.is_verified,
                    "last_login": user.last_login,
                    "created_at": user.created_at,
                    "roles": role_names,
                    "permissions": user_permissions,
                    "apiAccess": {
                        "heartbeat": True,  # Default values - could be made configurable
                        "s3": True,
                        "manualTest": True
                    }
                }
                result.append(user_dict)
            return result
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def get_all_roles(self, db: Session) -> List[Role]:
        """Get all available roles"""
        try:
            return db.query(Role).all()
        except Exception as e:
            logger.error(f"Error getting all roles: {e}")
            return []
    
    def delete_user(self, db: Session, username: str) -> bool:
        """Delete a user"""
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                return False
            
            # Delete user roles first
            db.query(UserRole).filter(UserRole.user_id == user.id).delete()
            
            # Delete the user
            db.delete(user)
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting user {username}: {e}")
            db.rollback()
            return False
    
    def update_user_permissions(self, db: Session, username: str, permissions: dict) -> bool:
        """Update user permissions"""
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                return False
            
            # Update user permissions based on the permissions dict
            # This could include API access control, role changes, etc.
            # For now, we'll implement basic permission updates
            
            # If role is specified, update it
            if 'role' in permissions:
                new_role_name = permissions['role']
                new_role = db.query(Role).filter(Role.name == new_role_name).first()
                if new_role:
                    # Remove existing roles
                    db.query(UserRole).filter(UserRole.user_id == user.id).delete()
                    # Assign new role
                    user_role = UserRole(user_id=user.id, role_id=new_role.id)
                    db.add(user_role)
            
            # Update other user fields if provided
            if 'first_name' in permissions:
                user.first_name = permissions['first_name']
            if 'last_name' in permissions:
                user.last_name = permissions['last_name']
            if 'email' in permissions:
                user.email = permissions['email']
            if 'is_active' in permissions:
                user.is_active = permissions['is_active']
            
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating user permissions for {username}: {e}")
            db.rollback()
            return False
    
    def assign_role_to_user(self, db: Session, username: str, role_name: str) -> bool:
        """Assign a role to a user"""
        try:
            user = db.query(User).filter(User.username == username).first()
            role = db.query(Role).filter(Role.name == role_name).first()
            
            if not user or not role:
                return False
            
            # Check if user already has this role
            existing_role = db.query(UserRole).filter(
                UserRole.user_id == user.id,
                UserRole.role_id == role.id
            ).first()
            
            if existing_role:
                return True  # User already has this role
            
            # Assign the role
            user_role = UserRole(user_id=user.id, role_id=role.id)
            db.add(user_role)
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Error assigning role {role_name} to user {username}: {e}")
            db.rollback()
            return False

# Global auth service instance
auth_service = AuthService()

# Dependency functions
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token"""
    try:
        token = credentials.credentials
        payload = auth_service.verify_token(token)
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    
    return user

def require_permission(resource: str, action: str):
    """Dependency function to require specific permission"""
    def permission_dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ):
        if not auth_service.has_permission(db, current_user.id, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: {resource}:{action}"
            )
        return current_user
    return permission_dependency

# Predefined roles and permissions
DEFAULT_ROLES = {
    "admin": {
        "description": "Full system administrator",
        "permissions": {
            "heartbeat": ["read", "write", "delete"],
            "s3": ["read", "write", "delete"],
            "manual_test": ["read", "write", "delete"],
            "system": ["read", "write", "delete"],
            "grafana": ["read", "write", "delete"],
            "users": ["read", "write", "delete"],
            "roles": ["read", "write", "delete"],
            "api_management": ["read", "write", "delete"]
        }
    },
    "manager": {
        "description": "Team manager with elevated access",
        "permissions": {
            "heartbeat": ["read", "write"],
            "s3": ["read", "write"],
            "manual_test": ["read", "write"],
            "system": ["read", "write"],
            "grafana": ["read", "write"],
            "users": ["read"],
            "roles": ["read"],
            "api_management": ["read"]
        }
    },
    "viewer": {
        "description": "Basic viewer with read-only access",
        "permissions": {
            "heartbeat": ["read"],
            "s3": ["read"],
            "manual_test": ["read"],
            "system": ["read"],
            "grafana": ["read"],
            "users": [],
            "roles": [],
            "api_management": []
        }
    }
}