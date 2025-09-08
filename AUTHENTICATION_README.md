# 🔐 Authentication System Documentation

## Overview

The Integrated Monitor now includes a comprehensive authentication system with role-based access control (RBAC). This system provides secure user authentication, authorization, and permission management.

## Features

- **User Authentication**: Secure login/logout with JWT tokens
- **Role-Based Access Control**: Three predefined roles with different permission levels
- **Permission Management**: Granular control over what users can access and modify
- **User Registration**: Self-service user registration with automatic role assignment
- **Session Management**: JWT-based session handling with configurable expiration

## 🚀 Quick Start

### 1. Install Dependencies

The authentication system requires additional Python packages. Install them using:

```bash
pip install bcrypt python-jose[cryptography] passlib
```

### 2. Set Environment Variables

Add these environment variables to your `.env` file:

```bash
# Authentication Configuration
SECRET_KEY=your-super-secret-key-change-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Database (if not already set)
DATABASE_URL=sqlite:///./data/api_monitor.db
```

### 3. Start the Backend

```bash
python3 -m app.main
```

### 4. Initialize the Authentication System

Run the initialization script to create default roles and an admin user:

```bash
python3 init_auth.py
```

This will create:
- Default roles (admin, manager, viewer)
- Admin user with credentials:
  - Username: `admin`
  - Password: `admin123`
  - Email: `admin@integratedmonitor.com`

### 5. Start the Frontend

```bash
cd integrated-monitor-ui
npm start
```

Navigate to `http://localhost:5000` and log in with the admin credentials.

## 👥 User Roles & Permissions

### Admin Role
**Full system access with all permissions**

- **Heartbeat Monitoring**: Read, Write, Delete
- **S3 Monitoring**: Read, Write, Delete
- **Manual Testing**: Read, Write, Delete
- **System Management**: Read, Write, Delete
- **Grafana Integration**: Read, Write, Delete
- **User Management**: Read, Write, Delete
- **Role Management**: Read, Write, Delete

### Manager Role
**Elevated access for team leaders**

- **Heartbeat Monitoring**: Read, Write
- **S3 Monitoring**: Read, Write
- **Manual Testing**: Read, Write
- **System Management**: Read, Write
- **Grafana Integration**: Read, Write
- **User Management**: Read only
- **Role Management**: Read only

### Viewer Role
**Read-only access for basic users**

- **Heartbeat Monitoring**: Read only
- **S3 Monitoring**: Read only
- **Manual Testing**: Read only
- **System Management**: Read only
- **Grafana Integration**: Read only

## 🔧 API Endpoints

### Authentication Endpoints

#### POST `/api/auth/login`
User login endpoint.

**Request Body:**
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@integratedmonitor.com",
    "roles": ["admin"],
    "is_active": true
  }
}
```

#### POST `/api/auth/register`
User registration endpoint.

**Request Body:**
```json
{
  "username": "newuser",
  "email": "user@example.com",
  "password": "password123",
  "first_name": "John",
  "last_name": "Doe"
}
```

#### GET `/api/auth/me`
Get current user information (requires authentication).

**Headers:**
```
Authorization: Bearer <access_token>
```

#### POST `/api/auth/init-roles`
Initialize default roles in the system (can be run multiple times safely).

### Protected Endpoints

All existing monitoring endpoints now require authentication. Include the JWT token in the Authorization header:

```
Authorization: Bearer <access_token>
```

## 🎨 Frontend Integration

### Authentication Context

The frontend uses React Context for authentication state management:

```typescript
import { useAuth } from '../contexts/AuthContext';

const { user, isAuthenticated, login, logout, hasPermission } = useAuth();
```

### Protected Routes

Use the `ProtectedRoute` component for role-based access control:

```typescript
import { ProtectedRoute } from '../components/ProtectedRoute';

// Require specific permission
<ProtectedRoute requiredPermission={{ resource: 'heartbeat', action: 'write' }}>
  <HeartbeatMonitoring />
</ProtectedRoute>

// Require specific role
<ProtectedRoute requiredRole="admin">
  <AdminPanel />
</ProtectedRoute>
```

### Permission Checks

Check user permissions in components:

```typescript
const { hasPermission, hasRole } = useAuth();

// Check if user can write to heartbeat monitoring
if (hasPermission('heartbeat', 'write')) {
  // Show edit buttons
}

// Check if user has admin role
if (hasRole('admin')) {
  // Show admin features
}
```

## 🛡️ Security Features

### Password Security
- Passwords are hashed using bcrypt with salt
- Minimum password length: 6 characters
- Passwords are never stored in plain text

### JWT Security
- Tokens expire after 30 minutes (configurable)
- Uses HS256 algorithm for signing
- Tokens are stored in localStorage (consider httpOnly cookies for production)

### Input Validation
- Username and email uniqueness validation
- Email format validation
- Password confirmation matching

## 📝 Database Schema

### Users Table
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    last_login TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

### Roles Table
```sql
CREATE TABLE roles (
    id INTEGER PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    description VARCHAR(200),
    permissions JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

### User Roles Table
```sql
CREATE TABLE user_roles (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    role_id INTEGER REFERENCES roles(id),
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 🔄 Adding New Roles

To add custom roles, you can extend the `DEFAULT_ROLES` configuration in `app/services/auth_service.py`:

```python
CUSTOM_ROLES = {
    "analyst": {
        "description": "Data analyst with read access and limited write",
        "permissions": {
            "heartbeat": ["read"],
            "s3": ["read", "write"],
            "manual_test": ["read"],
            "system": ["read"],
            "grafana": ["read", "write"]
        }
    }
}
```

## 🚨 Production Considerations

### Security
- Change the default `SECRET_KEY` to a strong, unique key
- Use HTTPS in production
- Consider using httpOnly cookies instead of localStorage for tokens
- Implement rate limiting for login attempts
- Add password complexity requirements

### Database
- Use a production-grade database (PostgreSQL, MySQL)
- Implement database connection pooling
- Set up regular backups

### Monitoring
- Log authentication events
- Monitor failed login attempts
- Set up alerts for suspicious activity

## 🐛 Troubleshooting

### Common Issues

1. **"No module named 'bcrypt'"**
   ```bash
   pip install bcrypt
   ```

2. **"JWT decode error"**
   - Check if `SECRET_KEY` is set correctly
   - Verify token expiration

3. **"User not found"**
   - Ensure the user exists in the database
   - Check if the user is active

4. **"Insufficient permissions"**
   - Verify user roles are assigned correctly
   - Check permission requirements for the endpoint

### Debug Mode

Enable debug logging by setting the log level:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 📚 Additional Resources

- [FastAPI Security Documentation](https://fastapi.tiangolo.com/tutorial/security/)
- [JWT.io](https://jwt.io/) - JWT token debugger
- [bcrypt Documentation](https://github.com/pyca/bcrypt/)

## 🤝 Contributing

When adding new features that require authentication:

1. Add permission checks to existing endpoints
2. Update the role permissions in `DEFAULT_ROLES`
3. Add appropriate frontend permission checks
4. Update this documentation

## 📄 License

This authentication system is part of the Integrated Monitor project and follows the same license terms.
