from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, Text, JSON
from sqlalchemy.sql import func
from pydantic import BaseModel, validator
from typing import Optional, Dict, Any, List
from datetime import datetime
import json

from .session import Base


# SQLAlchemy Models
class APIHeartbeatConfig(Base):
    __tablename__ = "api_heartbeat_configs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    method = Column(String, default="GET")
    headers = Column(JSON, default={})
    body = Column(Text, nullable=True)
    expected_status = Column(JSON, default=[200])
    expected_response = Column(Text, nullable=True)
    interval_minutes = Column(Integer, default=1)
    timeout_seconds = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class HeartbeatResult(Base):
    __tablename__ = "heartbeat_results"
    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, nullable=False)
    status_code = Column(Integer, nullable=True)
    response_time_ms = Column(Float, nullable=True)
    is_success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    response_body = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class S3BucketConfig(Base):
    __tablename__ = "s3_bucket_configs"
    id = Column(Integer, primary_key=True, index=True)
    bucket_name = Column(String, nullable=False)
    region = Column(String, nullable=False)
    access_key = Column(String, nullable=True)
    secret_key = Column(String, nullable=True)
    log_prefix = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class S3LogEntry(Base):
    __tablename__ = "s3_log_entries"
    id = Column(Integer, primary_key=True, index=True)
    bucket_id = Column(Integer, nullable=False)
    log_key = Column(String, nullable=False)
    log_size = Column(Integer, nullable=True)
    log_content = Column(Text, nullable=True)
    parsed_data = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class ManualTestConfig(Base):
    __tablename__ = "manual_test_configs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    method = Column(String, default="GET")
    headers = Column(JSON, default={})
    body = Column(Text, nullable=True)
    expected_status = Column(JSON, default=[200])
    expected_response = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ManualTestResult(Base):
    __tablename__ = "manual_test_results"
    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, nullable=False)
    status_code = Column(Integer, nullable=True)
    response_time_ms = Column(Float, nullable=True)
    is_success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    response_body = Column(Text, nullable=True)
    test_by = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class S3APIConfig(Base):
    __tablename__ = "s3_api_configs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    method = Column(String, default="GET")
    expected_status = Column(JSON, default=[200])
    headers = Column(JSON, default={})
    body = Column(Text, nullable=True)
    expected_response = Column(Text, nullable=True)
    s3_pattern = Column(String, nullable=True)
    bucket_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class S3APIStatus(Base):
    __tablename__ = "s3_api_status"
    id = Column(Integer, primary_key=True, index=True)
    api_config_id = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    source = Column(String, nullable=True)
    consecutive_down_cycles = Column(Integer, default=0)
    last_check = Column(DateTime(timezone=True), server_default=func.now())
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class S3APILog(Base):
    __tablename__ = "s3_api_logs"
    id = Column(Integer, primary_key=True, index=True)
    api_url = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    request_processing_time = Column(Float, nullable=True)
    target_processing_time = Column(Float, nullable=True)
    response_processing_time = Column(Float, nullable=True)
    elb_status_code = Column(Integer, nullable=True)
    target_status_code = Column(Integer, nullable=True)
    bucket_name = Column(String, nullable=False)
    api_config_id = Column(Integer, nullable=True)
    request_path = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    client_ip = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Pydantic Models for API requests/responses
class APIHeartbeatConfigCreate(BaseModel):
    name: str
    url: str
    method: str = "GET"
    headers: Dict[str, str] = {}
    body: Optional[str] = None
    expected_status: List[int] = [200]
    expected_response: Optional[str] = None
    interval_minutes: int = 1
    timeout_seconds: int = 30

    @validator('expected_status', pre=True)
    def validate_expected_status(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(',') if x.strip().isdigit()]
        elif isinstance(v, int):
            return [v]
        elif isinstance(v, list):
            return [int(x) for x in v]
        else:
            raise ValueError('expected_status must be int/list/csv string')

    @validator('headers', pre=True)
    def validate_headers(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else {}
            except json.JSONDecodeError:
                raise ValueError('headers must be valid JSON string')
        elif isinstance(v, dict):
            return v
        else:
            return {}


class APIHeartbeatConfigResponse(APIHeartbeatConfigCreate):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class HeartbeatResultResponse(BaseModel):
    id: int
    config_id: int
    status_code: Optional[int]
    response_time_ms: Optional[float]
    is_success: bool
    error_message: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True


class S3BucketConfigCreate(BaseModel):
    bucket_name: str
    region: str
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    log_prefix: Optional[str] = None


class S3BucketConfigResponse(S3BucketConfigCreate):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class S3LogEntryResponse(BaseModel):
    id: int
    bucket_id: int
    log_key: str
    log_size: Optional[int]
    log_content: Optional[str]
    parsed_data: Optional[Dict[str, Any]]
    timestamp: datetime

    class Config:
        from_attributes = True


class S3APILogResponse(BaseModel):
    id: int
    api_url: str
    timestamp: datetime
    request_processing_time: Optional[float]
    target_processing_time: Optional[float]
    response_processing_time: Optional[float]
    elb_status_code: Optional[int]
    target_status_code: Optional[int]
    bucket_name: str
    api_config_id: Optional[int]
    request_path: Optional[str]
    user_agent: Optional[str]
    client_ip: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ManualTestConfigCreate(BaseModel):
    name: str
    url: str
    method: str = "GET"
    headers: Dict[str, str] = {}
    body: Optional[str] = None
    expected_status: List[int] = [200]
    expected_response: Optional[str] = None

    @validator('expected_status', pre=True)
    def validate_expected_status_manual(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(',') if x.strip().isdigit()]
        elif isinstance(v, int):
            return [v]
        elif isinstance(v, list):
            return [int(x) for x in v]
        else:
            raise ValueError('expected_status must be int/list/csv string')

    @validator('headers', pre=True)
    def validate_headers_manual(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else {}
            except json.JSONDecodeError:
                raise ValueError('headers must be valid JSON string')
        elif isinstance(v, dict):
            return v
        else:
            return {}


class ManualTestConfigResponse(ManualTestConfigCreate):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ManualTestRequest(BaseModel):
    config_id: int
    test_by: Optional[str] = None


class ManualTestResultResponse(BaseModel):
    id: int
    config_id: int
    status_code: Optional[int]
    response_time_ms: Optional[float]
    is_success: bool
    error_message: Optional[str]
    test_by: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True


class S3APIConfigCreate(BaseModel):
    name: str
    url: str
    method: str = "GET"
    expected_status: List[int] = [200]
    headers: Dict[str, str] = {}
    body: Optional[str] = None
    expected_response: Optional[str] = None
    bucket_id: Optional[int] = None

    @validator('expected_status', pre=True)
    def validate_expected_status_s3api(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(',') if x.strip().isdigit()]
        elif isinstance(v, int):
            return [v]
        elif isinstance(v, list):
            return [int(x) for x in v]
        else:
            raise ValueError('expected_status must be int/list/csv string')

    @validator('headers', pre=True)
    def validate_headers_s3api(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else {}
            except json.JSONDecodeError:
                raise ValueError('headers must be valid JSON string')
        elif isinstance(v, dict):
            return v
        else:
            return {}


class S3APIConfigResponse(S3APIConfigCreate):
    id: int
    s3_pattern: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class S3APIStatusResponse(BaseModel):
    id: int
    api_config_id: int
    status: str
    source: Optional[str]
    consecutive_down_cycles: int
    last_check: datetime
    timestamp: datetime

    class Config:
        from_attributes = True


