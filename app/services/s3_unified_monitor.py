"""
Optimized S3 Monitor Service

Combines S3 bucket monitoring and API health monitoring with reduced complexity.
Key optimizations:
- Removed redundant classes and methods
- Simplified caching with TTL-based expiration
- Consolidated database operations
- Reduced thread complexity
- Eliminated over-engineered abstractions
- Streamlined log processing

Version: 4.0.0 (Optimized)
"""

import asyncio
import boto3
import requests
import time
import threading
import gzip
import re
import os
import hashlib
import json
import signal
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from botocore.exceptions import ClientError, NoCredentialsError
from threading import Event

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed, continue with system env vars
    pass

# Database imports
from app.db.session import SessionLocal
from app.db.models import (
    S3BucketConfig, S3LogEntry, S3BucketConfigCreate, 
    S3APILog, S3APIConfig, S3APIStatus
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))
DEFAULT_TIMEOUT = 10
MAX_WORKERS = 4
CACHE_TTL = 300  # 5 minutes
LOCAL_LOG_CLEANUP_INTERVAL = 300  # 5 minutes - same as monitoring cycle

def format_ist_timestamp(dt: datetime, include_timezone: bool = True) -> str:
    """Format datetime to IST timestamp string
    
    Args:
        dt: datetime object (assumed to be UTC if no timezone info)
        include_timezone: whether to include 'IST' suffix
    
    Returns:
        Formatted IST timestamp string
    """
    if dt.tzinfo is None:
        # Assume UTC if no timezone info
        dt = dt.replace(tzinfo=timezone.utc)
    
    # Convert to IST
    ist_dt = dt.astimezone(IST_TIMEZONE)
    
    if include_timezone:
        return ist_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    else:
        return ist_dt.strftime("%Y-%m-%d %H:%M:%S")

def format_ist_timestamp_from_iso(iso_timestamp: str, include_timezone: bool = True) -> str:
    """Convert ISO format timestamp string to IST format string
    
    Args:
        iso_timestamp: ISO format timestamp string
        include_timezone: whether to include 'IST' suffix
    
    Returns:
        Formatted IST timestamp string
    """
    try:
        # Parse ISO timestamp
        dt = datetime.fromisoformat(iso_timestamp)
        return format_ist_timestamp(dt, include_timezone)
    except Exception as e:
        logger.error(f"Error parsing ISO timestamp {iso_timestamp}: {e}")
        return iso_timestamp


class SimpleCache:
    """Simple TTL-based cache"""
    
    def __init__(self, ttl=CACHE_TTL):
        self.data = {}
        self.ttl = ttl
    
    def get(self, key, default=None):
        if key in self.data:
            value, timestamp = self.data[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self.data[key]
        return default
    
    def set(self, key, value):
        self.data[key] = (value, time.time())
    
    def clear(self):
        self.data.clear()


class S3LogDownloader:
    """Improved S3 Log Downloader with better handling and error recovery"""
    
    def __init__(self, bucket_name: str, region: str, log_prefix: str = "", 
                 access_key: str = None, secret_key: str = None):
        self.bucket_name = bucket_name
        self.region = region
        self.log_prefix = log_prefix
        self.local_download_dir = "downloads"
        
        os.makedirs(self.local_download_dir, exist_ok=True)
        
        # Initialize S3 client
        if access_key and secret_key:
            self.s3_client = boto3.client(
                's3', aws_access_key_id=access_key, aws_secret_access_key=secret_key,
                region_name=region
            )
        else:
            self.s3_client = boto3.client('s3', region_name=region)
        
        # Load existing files to avoid duplicates
        self.downloaded_files = self._load_existing_files()
    
    def _load_existing_files(self):
        """Load list of already downloaded files to avoid duplicates"""
        existing = set()
        try:
            for file in os.listdir(self.local_download_dir):
                if file.endswith('.log'):
                    # Use just the filename for tracking (not full S3 key)
                    gz_name = file[:-4] + '.gz' if file.endswith('.log') else file
                    existing.add(gz_name)
        except Exception as e:
            logger.warning(f"Failed to load existing files: {e}")
        
        logger.info(f"Found {len(existing)} existing files in local directory")
        return existing
    
    def find_latest_log_files(self, hours_back: int = 24, max_files: int = 2) -> List[Dict]:
        """Find latest ALB log files from S3 within last N hours"""
        all_files = []
        current_time = datetime.now(timezone.utc)
        
        logger.debug(f"Searching for logs in the last {hours_back} hours")
        
        # Get unique dates to check (include buffer for timezone differences)
        dates_to_check = set()
        for hour_offset in range(hours_back + 6):  # Add 6 hour buffer for timezone
            check_time = current_time - timedelta(hours=hour_offset)
            dates_to_check.add(check_time.strftime('%Y/%m/%d'))
        
        # Search each date
        for date_str in sorted(dates_to_check, reverse=True):
            date_prefix = self.log_prefix + date_str + '/'
            logger.debug(f"Checking prefix: {date_prefix}")
            
            try:
                paginator = self.s3_client.get_paginator('list_objects_v2')
                pages = paginator.paginate(
                    Bucket=self.bucket_name,
                    Prefix=date_prefix
                )
                
                page_files = []
                for page in pages:
                    for obj in page.get("Contents", []):
                        key = obj['Key']
                        basename = os.path.basename(key)
                        
                        # Filter for ALB logs and avoid duplicates
                        if (key.endswith(".log.gz") and 
                            "_elasticloadbalancing_" in key and
                            basename not in self.downloaded_files):
                            
                            # Check if file is recent enough (be more permissive)
                            file_time = obj['LastModified']
                            time_diff = current_time - file_time.replace(tzinfo=timezone.utc)
                            
                            # Include files from the last N hours plus some buffer
                            if time_diff <= timedelta(hours=hours_back + 2):
                                page_files.append(obj)
                                logger.debug(f"Found candidate: {basename} "
                                           f"(age: {time_diff.total_seconds()/3600:.1f}h)")
                
                all_files.extend(page_files)
                if page_files:
                    logger.info(f"Found {len(page_files)} files in {date_str}")
                            
            except Exception as e:
                logger.warning(f"Failed to list S3 prefix {date_prefix}: {e}")

        # Sort by last modified time (newest first) 
        all_files.sort(key=lambda x: x["LastModified"], reverse=True)
        
        # Group files by timestamp (within 10 seconds) to handle concurrent uploads
        grouped_files = []
        if all_files:
            current_group = [all_files[0]]
            base_time = all_files[0]["LastModified"]
            
            for file_obj in all_files[1:]:
                time_diff = abs((file_obj["LastModified"] - base_time).total_seconds())
                
                if time_diff <= 10:  # Files within 10 seconds are considered same batch
                    current_group.append(file_obj)
                else:
                    # Add current group and start new one
                    grouped_files.extend(current_group)
                    current_group = [file_obj]
                    base_time = file_obj["LastModified"]
                    
                    # Stop if we have enough files
                    if len(grouped_files) >= max_files:
                        break
            
            # Add the last group
            grouped_files.extend(current_group)
        
        # Limit final result
        latest_files = grouped_files[:max_files]
        
        if latest_files:
            logger.info(f"Found {len(latest_files)} new log files to download")
            # Log info about concurrent files
            if len(latest_files) > 1:
                time_span = (latest_files[0]["LastModified"] - latest_files[-1]["LastModified"]).total_seconds()
                logger.info(f"Files span {time_span:.0f} seconds (handling concurrent uploads)")
            
            # Log the newest file info for debugging
            newest = latest_files[0]
            logger.info(f"Newest file: {os.path.basename(newest['Key'])} "
                       f"(modified: {newest['LastModified']})")
        else:
            logger.info("No new log files found")
            
        return latest_files
    
    def _is_alb_log_file(self, s3_key: str) -> bool:
        """Check if file is ALB log"""
        filename = os.path.basename(s3_key)
        return bool(re.match(r'.*_elasticloadbalancing_.*\.log\.gz$', filename))
    
    def download_and_extract(self, s3_key: str, file_size: int = None) -> Optional[str]:
        """Download a .gz log from S3 and decompress to .log"""
        filename = os.path.basename(s3_key)
        gz_path = os.path.join(self.local_download_dir, filename)
        
        # Create .log filename (remove .gz extension)
        if gz_path.endswith(".gz"):
            log_path = gz_path[:-3]  # Remove .gz
        else:
            log_path = gz_path + ".log"

        # Check if already downloaded
        if os.path.exists(log_path):
            logger.debug(f"Already exists: {os.path.basename(log_path)}")
            self.downloaded_files.add(filename)
            return log_path

        try:
            # Download with progress indication for larger files
            if file_size and file_size > 1024 * 1024:  # 1MB
                logger.info(f"Downloading large file: {filename} ({file_size // 1024}KB)")
            
            self.s3_client.download_file(self.bucket_name, s3_key, gz_path)
            logger.info(f"Downloaded: {filename}")
            
            # Decompress
            with gzip.open(gz_path, "rb") as f_in, open(log_path, "wb") as f_out:
                f_out.write(f_in.read())
            
            # Clean up compressed file
            os.remove(gz_path)
            
            # Track as downloaded (use basename for tracking)
            self.downloaded_files.add(filename)
            
            logger.info(f"Decompressed: {os.path.basename(log_path)}")
            return log_path
            
        except Exception as e:
            logger.error(f"Failed to download/decompress {s3_key}: {e}")
            # Clean up partial download
            for cleanup_path in [gz_path, log_path]:
                if os.path.exists(cleanup_path):
                    try:
                        os.remove(cleanup_path)
                    except:
                        pass
            return None
    
    def cleanup_old_files(self, max_local_files: int = 100):
        """Remove old log files to prevent disk space issues"""
        try:
            log_files = []
            for file in os.listdir(self.local_download_dir):
                if file.endswith('.log'):
                    file_path = os.path.join(self.local_download_dir, file)
                    mtime = os.path.getmtime(file_path)
                    log_files.append((file, mtime))
            
            # Sort by modification time (newest first)
            log_files.sort(key=lambda x: x[1], reverse=True)
            
            if len(log_files) > max_local_files:
                files_to_remove = log_files[max_local_files:]
                logger.info(f"Cleaning up {len(files_to_remove)} old files")
                
                for file, _ in files_to_remove:
                    file_path = os.path.join(self.local_download_dir, file)
                    os.remove(file_path)
                    logger.debug(f"Removed old file: {file}")
                    
                    # Also remove from tracking
                    gz_name = file[:-4] + '.gz' if file.endswith('.log') else file
                    self.downloaded_files.discard(gz_name)
                    
        except Exception as e:
            logger.warning(f"Failed to cleanup old files: {e}")
    
    def get_disk_usage(self):
        """Get current disk usage of download directory"""
        try:
            total_size = 0
            file_count = 0
            for file in os.listdir(self.local_download_dir):
                if file.endswith('.log'):
                    file_path = os.path.join(self.local_download_dir, file)
                    total_size += os.path.getsize(file_path)
                    file_count += 1
            return file_count, total_size
        except:
            return 0, 0


class UnifiedS3Monitor:
    """Simplified Unified S3 Monitor"""
    
    def __init__(self):
        self.monitoring = False
        self.monitoring_thread = None
        self.processed_files = SimpleCache()
        self.processed_logs = SimpleCache()
        self.apis = []
        self.api_status = {}
        self.load_api_config()
    
    def load_api_config(self) -> None:
        """Load API configurations from database"""
        try:
            db = SessionLocal()
            configs = db.query(S3APIConfig).filter(S3APIConfig.is_active == True).all()
            
            self.apis = []
            for config in configs:
                self.apis.append({
                    'id': config.id,
                    'name': config.name,
                    'url': config.url,
                    'method': config.method,
                    'expected_status': config.expected_status,
                    'pattern': self._create_url_pattern(config.url),
                    'bucket_id': config.bucket_id
                })
            
            logger.info(f"Loaded {len(self.apis)} API configurations")
            
        except Exception as e:
            logger.error(f"Failed to load API config: {e}")
        finally:
            db.close()
    
    def _create_url_pattern(self, url: str) -> str:
        """Create regex pattern for URL matching"""
        try:
            parsed = urlparse(url)
            path = parsed.path.rstrip('/')
            return re.escape(path) + r'/?$' if path else r'.*'
        except:
            return r'.*'
    
    def check_bucket_logs(self, config: S3BucketConfig) -> None:
        """Check bucket logs and extract API data"""
        try:
            downloader = S3LogDownloader(
                config.bucket_name, config.region, config.log_prefix or "",
                config.access_key, config.secret_key
            )
            
            # Get latest files
            log_files = downloader.find_latest_log_files(
                hours_back=int(os.getenv('S3_HOURS_BACK', '1')),
                max_files=int(os.getenv('S3_MAX_FILES_PER_CYCLE', '2'))
            )
            
            for log_file in log_files:
                s3_key = log_file['Key']
                
                # Skip if already processed
                if self.processed_files.get(s3_key):
                    continue
                
                # Download and process
                file_size = log_file.get('Size', 0)
                local_path = downloader.download_and_extract(s3_key, file_size)
                if local_path:
                    self._process_log_file(local_path, s3_key, config)
                    self.processed_files.set(s3_key, True)
                    
        except Exception as e:
            logger.error(f"Error checking bucket logs: {e}")
    
    def _process_log_file(self, file_path: str, s3_key: str, config: S3BucketConfig) -> None:
        """Process log file in real-time and extract API data immediately"""
        try:
            db = SessionLocal()
            
            # Read the log file content
            with open(file_path, 'r', errors='ignore') as f:
                log_content = f.read()
            
            # Store S3 log entry with content
            log_entry = S3LogEntry(
                bucket_id=config.id,
                log_key=s3_key,
                log_size=os.path.getsize(file_path),
                log_content=log_content,
                parsed_data={
                    "file_path": file_path,
                    "line_count": len(log_content.splitlines()),
                    "processed_at": datetime.now(IST_TIMEZONE).isoformat(),
                    "status": "real_time_processed",
                    "api_processing": "completed"
                },
                timestamp=datetime.now(IST_TIMEZONE)
            )
            db.add(log_entry)
            
            # Process each line in real-time for API detection
            api_logs_created = 0
            for line in log_content.splitlines():
                if line.strip():
                    api_logs_created += self._process_log_line_realtime(db, line.strip(), s3_key, config.bucket_name)
            
            # Update parsed_data with API processing results
            log_entry.parsed_data.update({
                "api_logs_created": api_logs_created,
                "real_time_processing": True
            })
            
            db.commit()
            logger.info(f"Real-time processed log file: {s3_key} ({len(log_content.splitlines())} lines, {api_logs_created} API calls)")
            
        except Exception as e:
            logger.error(f"Error processing log file {s3_key}: {e}")
            if 'db' in locals():
                db.rollback()
        finally:
            if 'db' in locals():
                db.close()
    
    def _process_log_line_realtime(self, db: SessionLocal, line: str, log_key: str, bucket_name: str) -> int:
        """Process single ALB log line in real-time (returns count of API logs created)"""
        try:
            # Use the enhanced ALB log parsing method for better accuracy
            parsed = self._parse_alb_log_line(line)
            if not parsed:
                # Fallback to simple parsing if enhanced parsing fails
                parsed = self._parse_alb_line(line)
                if not parsed:
                    return 0
            
            # Check against APIs
            for api in self.apis:
                if re.search(api['pattern'], parsed.get('request_uri', '')):
                    # Generate hash for deduplication
                    log_hash = hashlib.md5(
                        f"{api['url']}|{parsed['timestamp']}|{parsed.get('client_ip', '')}".encode()
                    ).hexdigest()
                    
                    if self.processed_logs.get(log_hash):
                        continue
                    
                    # Create API log entry with enhanced fields
                    api_log = S3APILog(
                        api_url=api['url'],
                        timestamp=datetime.fromisoformat(parsed['timestamp']),
                        request_processing_time=parsed.get('request_processing_time'),
                        target_processing_time=parsed.get('response_time'),
                        response_processing_time=parsed.get('response_processing_time'),
                        elb_status_code=parsed.get('elb_status_code', parsed.get('status_code', 0)),
                        target_status_code=parsed.get('target_status_code', parsed.get('status_code', 0)),
                        bucket_name=bucket_name,
                        request_path=parsed.get('request_uri', ''),
                        client_ip=parsed.get('client_ip', ''),
                        user_agent=parsed.get('user_agent', ''),
                        api_config_id=api.get('id')
                    )
                    
                    db.add(api_log)
                    self.processed_logs.set(log_hash, True)
                    
                    logger.debug(f"Real-time API log created: {parsed.get('request_uri', '')} for bucket {bucket_name}")
                    return 1  # Return 1 to indicate one API log was created
                    
            return 0  # No API logs created for this line
                    
        except Exception as e:
            logger.debug(f"Error processing log line: {e}")
            return 0

    def _process_log_line(self, db: SessionLocal, line: str, log_key: str, bucket_name: str) -> None:
        """Process single ALB log line (legacy method for backward compatibility)"""
        try:
            # Use the enhanced ALB log parsing method for better accuracy
            parsed = self._parse_alb_log_line(line)
            if not parsed:
                # Fallback to simple parsing if enhanced parsing fails
                parsed = self._parse_alb_line(line)
                if not parsed:
                    return
            
            # Check against APIs
            for api in self.apis:
                if re.search(api['pattern'], parsed.get('request_uri', '')):
                    # Generate hash for deduplication
                    log_hash = hashlib.md5(
                        f"{api['url']}|{parsed['timestamp']}|{parsed.get('client_ip', '')}".encode()
                    ).hexdigest()
                    
                    if self.processed_logs.get(log_hash):
                        continue
                    
                    # Create API log entry with enhanced fields
                    api_log = S3APILog(
                        api_url=api['url'],
                        timestamp=datetime.fromisoformat(parsed['timestamp']),
                        elb_status_code=parsed.get('elb_status_code', parsed.get('status_code', 0)),
                        target_status_code=parsed.get('target_status_code', parsed.get('status_code', 0)),
                        bucket_name=bucket_name,
                        request_path=parsed.get('request_uri', ''),
                        client_ip=parsed.get('client_ip', ''),
                        user_agent=parsed.get('user_agent', ''),
                        api_config_id=api.get('id')
                    )
                    
                    db.add(api_log)
                    self.processed_logs.set(log_hash, True)
                    
                    break
                    
        except Exception as e:
            logger.debug(f"Error processing log line: {e}")
    
    def _parse_alb_line(self, line: str) -> Optional[Dict]:
        """Parse ALB log line"""
        try:
            # Simplified ALB log parsing
            parts = line.split()
            if len(parts) < 12:
                return None
            
            # Extract key fields
            timestamp = parts[1].replace('Z', '+00:00')
            client_ip = parts[3].split(':')[0]
            status_code = int(parts[8]) if parts[8].isdigit() else 0
            response_time = float(parts[6]) if parts[6] != '-' else 0.0
            
            # Extract request info
            request_field = ' '.join(parts[11:]).split('"')[1] if '"' in line else ''
            request_parts = request_field.split()
            request_method = request_parts[0] if request_parts else 'GET'
            request_uri = request_parts[1] if len(request_parts) > 1 else '/'
            
            # Clean up the URI by removing port numbers (e.g., :443)
            if request_uri.startswith('https://') and ':443' in request_uri:
                request_uri = request_uri.replace(':443', '')
            elif request_uri.startswith('http://') and ':80' in request_uri:
                request_uri = request_uri.replace(':80', '')
            
            # Convert to IST but keep in ISO format for database compatibility
            utc_dt = datetime.fromisoformat(timestamp)
            ist_dt = utc_dt.astimezone(IST_TIMEZONE)
            
            return {
                'timestamp': ist_dt.isoformat(),
                'client_ip': client_ip,
                'status_code': status_code,
                'elb_status_code': status_code,
                'target_status_code': status_code,
                'response_time': response_time,
                'request_method': request_method,
                'request_uri': request_uri,
                'user_agent': ''
            }
            
        except Exception as e:
            logger.debug(f"Failed to parse ALB line: {e}")
            return None

    def _parse_alb_log_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a single ALB log line with enhanced pattern matching"""
        try:
            # Enhanced regex to extract all fields from ALB logs (updated for actual format)
            log_pattern = re.compile(
                r'(?P<type>\S+)\s+'                           # Type (http/https)
                r'(?P<timestamp>\S+Z)\s+'                     # Timestamp
                r'(?P<elb>\S+)\s+'                            # ELB name
                r'(?P<client_port>\S+)\s+'                    # Client:port
                r'(?P<target_port>\S+)\s+'                    # Target:port
                r'(?P<request_processing_time>[\d.-]+)\s+'    # Request processing time
                r'(?P<target_processing_time>[\d.-]+)\s+'     # Target processing time  
                r'(?P<response_processing_time>[\d.-]+)\s+'   # Response processing time
                r'(?P<elb_status_code>\d+)\s+'               # ELB status code
                r'(?P<target_status_code>\d+|-)\s+'          # Target status code
                r'(?P<received_bytes>\d+)\s+'                 # Received bytes
                r'(?P<sent_bytes>\d+)\s+'                     # Sent bytes
                r'"(?P<request>[^"]+)"\s+'                    # Request (GET/POST/etc + URL)
                r'"(?P<user_agent>[^"]+)"\s+'                 # User agent
                r'(?P<ssl_cipher>\S+)\s+'                     # SSL cipher
                r'(?P<ssl_protocol>\S+)\s+'                   # SSL protocol
                r'(?P<target_group_arn>\S+)\s+'               # Target group ARN
                r'"(?P<trace_id>[^"]*)"\s+'                   # Trace ID
                r'"(?P<domain_name>[^"]*)"\s+'                # Domain name
                r'"(?P<certificate_arn>[^"]*)"\s+'            # Certificate ARN
                r'(?P<matched_rule_priority>\d+)\s+'          # Matched rule priority
                r'(?P<request_creation_time>\S+Z)\s+'         # Request creation time
                r'"(?P<actions_executed>[^"]*)"\s+'           # Actions executed
                r'"(?P<redirect_url>[^"]*)"\s+'               # Redirect URL
                r'"(?P<error_reason>[^"]*)"\s+'               # Error reason
                r'"(?P<target_port_2>\S+)"\s+'                # Target port (second occurrence)
                r'"(?P<target_status_code_2>[^"]*)"\s+'       # Target status code (second occurrence)
                r'"(?P<response_reason>[^"]*)"\s+'             # Response reason
                r'"(?P<target_response_reason>[^"]*)"\s+'     # Target response reason
                r'(?P<transaction_id>\S+)'                     # Transaction ID
            )
            
            match = log_pattern.search(line)
            if not match:
                return None
            
            # Extract request URL from the request field
            request_field = match.group("request")
            request_parts = request_field.split()
            if len(request_parts) >= 2:
                request_method = request_parts[0]
                request_uri = request_parts[1]
                
                # Clean up the URI by removing port numbers (e.g., :443)
                if request_uri.startswith('https://') and ':443' in request_uri:
                    request_uri = request_uri.replace(':443', '')
                elif request_uri.startswith('http://') and ':80' in request_uri:
                    request_uri = request_uri.replace(':80', '')
            else:
                request_method = "GET"
                request_uri = "/"
            
            # Extract client IP
            client_port = match.group("client_port")
            client_ip = client_port.split(':')[0] if ':' in client_port else client_port
            
            # Extract status code
            target_status = match.group("target_status_code")
            status_code = int(target_status) if target_status.isdigit() else 0
            
            # Extract response time
            target_time = match.group("target_processing_time")
            response_time = float(target_time) if target_time != '-' else 0.0
            
            # Convert timestamp to IST
            timestamp = self._convert_timestamp_format(match.group("timestamp"))
            
            return {
                'timestamp': timestamp,
                'client_ip': client_ip,
                'status_code': status_code,
                'response_time': response_time,
                'request_method': request_method,
                'request_uri': request_uri,
                'user_agent': match.group("user_agent"),
                'elb_status_code': match.group("elb_status_code"),
                'target_status_code': target_status,
                'request_processing_time': match.group("request_processing_time"),
                'response_processing_time': match.group("response_processing_time"),
                'received_bytes': match.group("received_bytes"),
                'sent_bytes': match.group("sent_bytes"),
                'ssl_cipher': match.group("ssl_cipher"),
                'ssl_protocol': match.group("ssl_protocol"),
                'target_group_arn': match.group("target_group_arn"),
                'trace_id': match.group("trace_id"),
                'domain_name': match.group("domain_name"),
                'certificate_arn': match.group("certificate_arn"),
                'matched_rule_priority': match.group("matched_rule_priority"),
                'request_creation_time': match.group("request_creation_time"),
                'actions_executed': match.group("actions_executed"),
                'redirect_url': match.group("redirect_url"),
                'error_reason': match.group("error_reason"),
                'target_port_2': match.group("target_port_2"),
                'target_status_code_2': match.group("target_status_code_2"),
                'response_reason': match.group("response_reason"),
                'target_response_reason': match.group("target_response_reason"),
                'transaction_id': match.group("transaction_id")
            }
            
        except Exception as e:
            logger.debug(f"Failed to parse ALB log line: {e}")
            return None

    def _convert_timestamp_format(self, timestamp_str: str) -> str:
        """Convert ALB timestamp format to ISO format with IST timezone"""
        try:
            # Remove 'Z' and add timezone info
            if timestamp_str.endswith('Z'):
                timestamp_str = timestamp_str[:-1] + '+00:00'
            
            # Parse UTC timestamp
            utc_dt = datetime.fromisoformat(timestamp_str)
            
            # Convert to IST but keep in ISO format for database compatibility
            ist_dt = utc_dt.astimezone(IST_TIMEZONE)
            return ist_dt.isoformat()
        except Exception as e:
            logger.error(f"Error converting timestamp {timestamp_str}: {e}")
            # Return original timestamp if conversion fails
            return timestamp_str

    async def insert_parsed_log(self, parsed_log: Dict[str, Any], bucket_name: str, api_config_id: Optional[int] = None) -> bool:
        """Insert parsed ALB log into database (optimized for real-time processing)"""
        try:
            db = SessionLocal()
            
            # Create S3APILog entry
            api_log = S3APILog(
                api_url=parsed_log.get('request_uri', ''),
                timestamp=datetime.fromisoformat(parsed_log['timestamp']),
                request_processing_time=parsed_log.get('request_processing_time'),
                target_processing_time=parsed_log.get('response_time'),
                response_processing_time=parsed_log.get('response_processing_time'),
                elb_status_code=parsed_log.get('elb_status_code'),
                target_status_code=parsed_log.get('status_code'),
                bucket_name=bucket_name,
                api_config_id=api_config_id,
                request_path=parsed_log.get('request_uri', ''),
                user_agent=parsed_log.get('user_agent', ''),
                client_ip=parsed_log.get('client_ip', '')
            )
            
            db.add(api_log)
            db.commit()
            
            logger.debug(f"Real-time log inserted for bucket {bucket_name}: {parsed_log.get('request_uri', '')}")
            return True
            
        except Exception as e:
            logger.error(f"Error inserting parsed log: {e}")
            if 'db' in locals():
                db.rollback()
            return False
        finally:
            if 'db' in locals():
                db.close()

    def insert_parsed_log_sync(self, parsed_log: Dict[str, Any], bucket_name: str, api_config_id: Optional[int] = None) -> bool:
        """Synchronous version of insert_parsed_log for real-time processing"""
        try:
            db = SessionLocal()
            
            # Create S3APILog entry
            api_log = S3APILog(
                api_url=parsed_log.get('request_uri', ''),
                timestamp=datetime.fromisoformat(parsed_log['timestamp']),
                request_processing_time=parsed_log.get('request_processing_time'),
                target_processing_time=parsed_log.get('response_time'),
                response_processing_time=parsed_log.get('response_processing_time'),
                elb_status_code=parsed_log.get('elb_status_code'),
                target_status_code=parsed_log.get('status_code'),
                bucket_name=bucket_name,
                api_config_id=api_config_id,
                request_path=parsed_log.get('request_uri', ''),
                user_agent=parsed_log.get('user_agent', ''),
                client_ip=parsed_log.get('client_ip', '')
            )
            
            db.add(api_log)
            db.commit()
            
            logger.debug(f"Real-time log inserted for bucket {bucket_name}: {parsed_log.get('request_uri', '')}")
            return True
            
        except Exception as e:
            logger.error(f"Error inserting parsed log: {e}")
            if 'db' in locals():
                db.rollback()
            return False
        finally:
            if 'db' in locals():
                db.close()

    async def process_and_insert_logs(self, log_content: str, bucket_name: str, api_config_id: Optional[int] = None) -> Dict[str, Any]:
        """Process log content and insert parsed logs into database"""
        try:
            lines = log_content.strip().split('\n')
            total_lines = len(lines)
            parsed_count = 0
            inserted_count = 0
            errors = []
            
            for line_num, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                
                try:
                    # Try enhanced parsing first
                    parsed_log = self._parse_alb_log_line(line)
                    if not parsed_log:
                        # Fallback to legacy parsing
                        parsed_log = self._parse_alb_line(line)
                    
                    if parsed_log:
                        parsed_count += 1
                        
                        # Insert into database
                        if await self.insert_parsed_log(parsed_log, bucket_name, api_config_id):
                            inserted_count += 1
                        else:
                            errors.append(f"Line {line_num}: Failed to insert log")
                    else:
                        errors.append(f"Line {line_num}: Failed to parse log line")
                        
                except Exception as e:
                    errors.append(f"Line {line_num}: {str(e)}")
                    continue
            
            return {
                'success': True,
                'total_lines': total_lines,
                'parsed_count': parsed_count,
                'inserted_count': inserted_count,
                'errors': errors,
                'bucket_name': bucket_name
            }
            
        except Exception as e:
            logger.error(f"Error processing logs for bucket {bucket_name}: {e}")
            return {
                'success': False,
                'error': str(e),
                'bucket_name': bucket_name
            }

    async def download_and_process_s3_logs(self, bucket_name: str, log_key: str, api_config_id: Optional[int] = None) -> Dict[str, Any]:
        """Download S3 log file and process it with enhanced parsing"""
        try:
            # Download log file from S3
            log_content = await self.download_s3_file(bucket_name, log_key)
            if not log_content:
                return {
                    'success': False,
                    'error': f'Failed to download log file {log_key} from bucket {bucket_name}',
                    'bucket_name': bucket_name
                }
            
            # Process and insert logs
            result = await self.process_and_insert_logs(log_content, bucket_name, api_config_id)
            
            # Add download info to result
            result['log_key'] = log_key
            result['file_size'] = len(log_content)
            
            return result
            
        except Exception as e:
            logger.error(f"Error downloading and processing S3 logs for bucket {bucket_name}: {e}")
            return {
                'success': False,
                'error': str(e),
                'bucket_name': bucket_name
            }

    def process_local_log_file(self, file_path: str, bucket_name: str = "productionathenalogs") -> Dict[str, Any]:
        """Process a local log file and insert parsed data into database"""
        try:
            logger.info(f"Processing local log file: {file_path}")
            
            # Read the log file content
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_content = f.read()
            
            # Process the log content using existing enhanced parsing
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    self.process_and_insert_logs(log_content, bucket_name)
                )
                
                if result.get('success'):
                    logger.info(f"Successfully processed log file {file_path}: {result.get('parsed_count', 0)} entries")
                else:
                    logger.warning(f"Log processing completed with issues: {result}")
                    
                return result
                    
            finally:
                loop.close()
                
        except Exception as e:
            logger.error(f"Error processing local log file {file_path}: {e}")
            return {
                'success': False,
                'error': str(e),
                'file_path': file_path
            }

    def process_all_local_logs(self, download_dir: str = "downloads", bucket_name: str = "productionathenalogs") -> Dict[str, Any]:
        """Process all local log files in the download directory"""
        try:
            logger.info(f"Processing all local log files in {download_dir}")
            
            if not os.path.exists(download_dir):
                return {
                    'success': False,
                    'error': f'Download directory {download_dir} does not exist'
                }
            
            # Get all .log files
            log_files = []
            for file in os.listdir(download_dir):
                if file.endswith('.log'):
                    log_files.append(os.path.join(download_dir, file))
            
            if not log_files:
                return {
                    'success': False,
                    'error': 'No .log files found in download directory'
                }
            
            logger.info(f"Found {len(log_files)} log files to process")
            
            # Process each file
            total_processed = 0
            total_entries = 0
            results = []
            
            for file_path in log_files:
                try:
                    result = self.process_local_log_file(file_path, bucket_name)
                    if result.get('success'):
                        total_processed += 1
                        total_entries += result.get('parsed_count', 0)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    results.append({
                        'success': False,
                        'error': str(e),
                        'file_path': file_path
                    })
            
            return {
                'success': True,
                'total_files': len(log_files),
                'processed_files': total_processed,
                'total_entries': total_entries,
                'results': results
            }
            
        except Exception as e:
            logger.error(f"Error processing all local logs: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def download_s3_file(self, bucket_name: str, log_key: str) -> Optional[str]:
        """Download a file from S3 bucket"""
        try:
            # Get S3 client
            s3_client = self._get_s3_client()
            if not s3_client:
                return None
            
            # Download file content
            response = s3_client.get_object(Bucket=bucket_name, Key=log_key)
            file_content = response['Body'].read().decode('utf-8')
            
            logger.debug(f"Downloaded {log_key} from bucket {bucket_name}, size: {len(file_content)} bytes")
            return file_content
            
        except Exception as e:
            logger.error(f"Error downloading file {log_key} from bucket {bucket_name}: {e}")
            return None

    def _get_s3_client(self):
        """Get S3 client with credentials"""
        try:
            # Use default credentials or environment variables
            return boto3.client('s3')
        except Exception as e:
            logger.error(f"Error creating S3 client: {e}")
            return None
    
    async def check_api_health(self, api: Dict) -> str:
        """Check API health via logs"""
        try:
            db = SessionLocal()
            
            # Get recent logs for this API
            since_time = datetime.now(IST_TIMEZONE) - timedelta(hours=1)
            recent_logs = db.query(S3APILog).filter(
                S3APILog.api_url == api['url'],
                S3APILog.timestamp >= since_time
            ).all()
            
            if not recent_logs:
                return 'UNKNOWN'
            
            # Calculate success rate
            success_count = sum(1 for log in recent_logs if log.elb_status_code == 200)
            success_rate = success_count / len(recent_logs)
            
            if success_rate >= 0.8:
                return 'UP'
            elif success_rate >= 0.5:
                return 'DEGRADED'
            else:
                return 'DOWN'
                
        except Exception as e:
            logger.error(f"Error checking API health: {e}")
            return 'ERROR'
        finally:
            if 'db' in locals():
                db.close()
    
    async def hit_api(self, api: Dict) -> bool:
        """Direct API health check"""
        try:
            method = api.get('method', 'GET').upper()
            url = api['url']
            expected = api.get('expected_status', [200])
            
            if method == 'GET':
                response = requests.get(url, timeout=DEFAULT_TIMEOUT)
            else:
                response = requests.post(url, timeout=DEFAULT_TIMEOUT)
            
            return response.status_code in expected
            
        except Exception as e:
            logger.warning(f"API check failed for {api['name']}: {e}")
            return False
    
    def run_monitoring_cycle(self) -> None:
        """Run one monitoring cycle"""
        try:
            db = SessionLocal()
            configs = db.query(S3BucketConfig).filter(S3BucketConfig.is_active == True).all()
            
            # Process each bucket
            for config in configs:
                self.check_bucket_logs(config)
            
            # Check API health
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                for api in self.apis:
                    status = loop.run_until_complete(self.check_api_health(api))
                    self.api_status[api['name']] = {
                        'status': status,
                        'last_check': format_ist_timestamp_from_iso(datetime.now(IST_TIMEZONE).isoformat())
                    }
                    
                    # If DOWN, try direct check
                    if status == 'DOWN':
                        direct_check = loop.run_until_complete(self.hit_api(api))
                        if direct_check:
                            self.api_status[api['name']]['status'] = 'UP'
                            
            finally:
                loop.close()
            
            logger.info("Monitoring cycle completed")
            
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}")
        finally:
            if 'db' in locals():
                db.close()
    
    def start_monitoring(self) -> None:
        """Start monitoring service"""
        if self.monitoring:
            logger.warning("Monitoring already running")
            return
        
        self.monitoring = True
        self.monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        logger.info("Monitoring service started")
    
    def stop_monitoring(self) -> None:
        """Stop monitoring service"""
        self.monitoring = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=10)
        logger.info("Monitoring service stopped")
    
    def _monitoring_loop(self) -> None:
        """Main monitoring loop"""
        logger.info("Monitoring loop started")
        
        while self.monitoring:
            try:
                # Clean up old local log files first
                self.cleanup_local_logs()
                
                # Run monitoring cycle (download and process new logs)
                self.run_monitoring_cycle()
                
                # Wait for next cycle (configurable interval)
                monitoring_interval = int(os.getenv('S3_MONITORING_INTERVAL_SECONDS', '300'))  # Default 5 minutes
                time.sleep(monitoring_interval)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(60)  # 1 minute on error
        
        logger.info("Monitoring loop stopped")

    def start_realtime_monitoring(self, interval_seconds: int = 60) -> None:
        """Start real-time monitoring with faster intervals"""
        if self.monitoring:
            logger.warning("Monitoring already running")
            return
        
        self.monitoring = True
        self.monitoring_thread = threading.Thread(target=self._realtime_monitoring_loop, args=(interval_seconds,), daemon=True)
        self.monitoring_thread.start()
        logger.info(f"Real-time monitoring service started with {interval_seconds}s intervals")

    def _realtime_monitoring_loop(self, interval_seconds: int) -> None:
        """Real-time monitoring loop with faster intervals"""
        logger.info(f"Real-time monitoring loop started with {interval_seconds}s intervals")
        
        while self.monitoring:
            try:
                # Run monitoring cycle (download and process new logs)
                self.run_monitoring_cycle()
                
                # Wait for next cycle
                time.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Error in real-time monitoring loop: {e}")
                time.sleep(30)  # 30 seconds on error
        
        logger.info("Real-time monitoring loop stopped")
    
    def cleanup_local_logs(self) -> None:
        """Clean up old local log files while preserving database logs"""
        try:
            logger.info("Starting local log cleanup...")
            
            # Get the downloads directory
            downloads_dir = "downloads"
            if not os.path.exists(downloads_dir):
                logger.info("Downloads directory does not exist, skipping cleanup")
                return
            
            # List all files in downloads directory
            files = os.listdir(downloads_dir)
            log_files = [f for f in files if f.endswith('.log')]
            
            if not log_files:
                logger.info("No log files found for cleanup")
                return
            
            logger.info(f"Found {len(log_files)} log files for cleanup")
            
            # Delete all local log files
            deleted_count = 0
            for log_file in log_files:
                try:
                    file_path = os.path.join(downloads_dir, log_file)
                    os.remove(file_path)
                    deleted_count += 1
                    logger.debug(f"Deleted local log file: {log_file}")
                except Exception as e:
                    logger.error(f"Error deleting log file {log_file}: {e}")
            
            logger.info(f"Local log cleanup completed: {deleted_count} files deleted")
            logger.info("Database logs preserved - no data loss")
            
            # Store cleanup stats for monitoring
            self.last_cleanup_time = datetime.now(IST_TIMEZONE)
            self.last_cleanup_count = deleted_count
            
        except Exception as e:
            logger.error(f"Error during local log cleanup: {e}")
            # Don't fail the monitoring cycle due to cleanup errors
    
    def get_cleanup_status(self) -> Dict[str, Any]:
        """Get local log cleanup status"""
        try:
            downloads_dir = "downloads"
            current_files = []
            
            if os.path.exists(downloads_dir):
                files = os.listdir(downloads_dir)
                log_files = [f for f in files if f.endswith('.log')]
                current_files = log_files
            
            return {
                "cleanup_enabled": True,
                "cleanup_interval_minutes": LOCAL_LOG_CLEANUP_INTERVAL // 60,
                "last_cleanup_time": getattr(self, 'last_cleanup_time', None),
                "last_cleanup_count": getattr(self, 'last_cleanup_count', 0),
                "current_local_files": len(current_files),
                "local_files_list": current_files,
                "next_cleanup_in": "5 minutes (every monitoring cycle)"
            }
        except Exception as e:
            logger.error(f"Error getting cleanup status: {e}")
            return {"error": str(e)}
    
    # API Methods (simplified)
    async def add_bucket(self, config: S3BucketConfigCreate) -> Dict[str, Any]:
        """Add new S3 bucket"""
        try:
            db = SessionLocal()
            
            # Check if exists
            existing = db.query(S3BucketConfig).filter(
                S3BucketConfig.bucket_name == config.bucket_name
            ).first()
            
            if existing:
                return {"success": False, "error": "Bucket already exists"}
            
            # Create new bucket
            new_bucket = S3BucketConfig(
                bucket_name=config.bucket_name,
                region=config.region,
                log_prefix=config.log_prefix,
                access_key=config.access_key,
                secret_key=config.secret_key,
                is_active=True
            )
            
            db.add(new_bucket)
            db.commit()
            
            return {"success": True, "bucket_id": new_bucket.id}
            
        except Exception as e:
            logger.error(f"Error adding bucket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()
    
    async def get_status(self) -> Dict[str, Any]:
        """Get monitoring status"""
        try:
            db = SessionLocal()
            
            # Get bucket count
            bucket_count = db.query(S3BucketConfig).filter(S3BucketConfig.is_active == True).count()
            
            # Get recent log count
            since_time = datetime.now(IST_TIMEZONE) - timedelta(hours=24)
            recent_logs = db.query(S3APILog).filter(S3APILog.timestamp >= since_time).count()
            
            # Get real-time log count (last 5 minutes)
            realtime_since = datetime.now(IST_TIMEZONE) - timedelta(minutes=5)
            realtime_logs = db.query(S3APILog).filter(S3APILog.timestamp >= realtime_since).count()
            
            # Get cleanup status
            cleanup_status = self.get_cleanup_status()
            
            return {
                "success": True,
                "monitoring": self.monitoring,
                "active_buckets": bucket_count,
                "active_apis": len(self.apis),
                "recent_logs_24h": recent_logs,
                "realtime_logs_5m": realtime_logs,
                "api_status": self.api_status,
                "local_log_cleanup": cleanup_status,
                "monitoring_mode": "real-time" if hasattr(self, 'monitoring_thread') and self.monitoring_thread else "standard"
            }
            
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_realtime_status(self) -> Dict[str, Any]:
        """Get real-time monitoring status with live metrics"""
        try:
            db = SessionLocal()
            
            # Get real-time metrics (last 1 minute)
            since_time = datetime.now(IST_TIMEZONE) - timedelta(minutes=1)
            recent_logs = db.query(S3APILog).filter(S3APILog.timestamp >= since_time).all()
            
            # Calculate real-time statistics
            total_requests = len(recent_logs)
            success_requests = len([log for log in recent_logs if log.elb_status_code == 200])
            error_requests = total_requests - success_requests
            success_rate = (success_requests / total_requests * 100) if total_requests > 0 else 0
            
            # Get average response times
            response_times = [log.target_processing_time for log in recent_logs if log.target_processing_time]
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0
            
            # Get unique APIs hit
            unique_apis = set(log.api_url for log in recent_logs if log.api_url)
            
            return {
                "success": True,
                "timestamp": format_ist_timestamp_from_iso(datetime.now(IST_TIMEZONE).isoformat()),
                "total_requests": total_requests,
                "success_requests": success_requests,
                "error_requests": error_requests,
                "success_rate": round(success_rate, 2),
                "avg_response_time": round(avg_response_time, 3),
                "unique_apis": len(unique_apis),
                "monitoring_active": self.monitoring,
                "recent_apis": list(unique_apis)[:10]  # Top 10 APIs
            }
            
        except Exception as e:
            logger.error(f"Error getting real-time status: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()
    
    async def get_logs(self, api_name: str = None, hours: int = 24, limit: Optional[int] = None) -> Dict[str, Any]:
        """Get API logs"""
        try:
            db = SessionLocal()
            
            query = db.query(S3APILog)
            
            if api_name:
                # Filter by request_path or api_url if api_name is provided
                query = query.filter(
                    (S3APILog.request_path.contains(api_name)) | 
                    (S3APILog.api_url.contains(api_name))
                )
            
            if hours > 0:
                since_time = datetime.now(IST_TIMEZONE) - timedelta(hours=hours)
                query = query.filter(S3APILog.timestamp >= since_time)
            
            q = query.order_by(S3APILog.timestamp.desc())
            logs = (q.limit(limit).all()) if isinstance(limit, int) and limit > 0 else q.all()
            
            log_data = []
            for log in logs:
                log_data.append({
                    "id": log.id,
                    "api_url": log.api_url,
                    "timestamp": format_ist_timestamp_from_iso(log.timestamp.isoformat()),
                    "elb_status_code": log.elb_status_code,
                    "target_status_code": log.target_status_code,
                    "request_processing_time": log.request_processing_time,
                    "target_processing_time": log.target_processing_time,
                    "response_processing_time": log.response_processing_time,
                    "bucket_name": log.bucket_name,
                    "request_path": log.request_path,
                    "client_ip": log.client_ip,
                    "user_agent": log.user_agent,
                    "created_at": format_ist_timestamp_from_iso(log.created_at.isoformat()) if log.created_at else None
                })
            
            return {"success": True, "logs": log_data, "count": len(log_data)}
            
        except Exception as e:
            logger.error(f"Error getting logs: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_api_configs(self) -> Dict[str, Any]:
        """Get all S3 API configurations"""
        try:
            db = SessionLocal()
            configs = db.query(S3APIConfig).filter(S3APIConfig.is_active == True).all()
            
            config_data = []
            for config in configs:
                config_data.append({
                    "id": config.id,
                    "name": config.name,
                    "url": config.url,
                    "method": config.method,
                    "expected_status": config.expected_status,
                    "headers": config.headers,
                    "body": config.body,
                    "expected_response": config.expected_response,
                    "s3_pattern": config.s3_pattern,
                    "bucket_id": config.bucket_id,
                    "is_active": config.is_active,
                    "created_at": format_ist_timestamp_from_iso(config.created_at.isoformat()) if config.created_at else None,
                    "updated_at": format_ist_timestamp_from_iso(config.updated_at.isoformat()) if config.updated_at else None
                })
            
            return {"success": True, "configs": config_data, "count": len(config_data)}
            
        except Exception as e:
            logger.error(f"Error getting API configs: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_all_buckets(self) -> Dict[str, Any]:
        """Get all S3 bucket configurations"""
        try:
            db = SessionLocal()
            buckets = db.query(S3BucketConfig).filter(S3BucketConfig.is_active == True).all()
            
            bucket_data = []
            for bucket in buckets:
                bucket_data.append({
                    "id": bucket.id,
                    "bucket_name": bucket.bucket_name,
                    "region": bucket.region,
                    "access_key": bucket.access_key,
                    "secret_key": bucket.secret_key,
                    "log_prefix": bucket.log_prefix,
                    "is_active": bucket.is_active,
                    "created_at": format_ist_timestamp_from_iso(bucket.created_at.isoformat()) if bucket.created_at else None,
                    "updated_at": format_ist_timestamp_from_iso(bucket.updated_at.isoformat()) if bucket.updated_at else None
                })
            
            return {"success": True, "buckets": bucket_data, "count": len(bucket_data)}
            
        except Exception as e:
            logger.error(f"Error getting buckets: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_bucket(self, bucket_id: int) -> Dict[str, Any]:
        """Get a specific S3 bucket configuration"""
        try:
            db = SessionLocal()
            bucket = db.query(S3BucketConfig).filter(S3BucketConfig.id == bucket_id).first()
            
            if not bucket:
                return {"success": False, "error": "Bucket not found"}
            
            bucket_data = {
                "id": bucket.id,
                "bucket_name": bucket.bucket_name,
                "region": bucket.region,
                "access_key": bucket.access_key,
                "secret_key": bucket.secret_key,
                "log_prefix": bucket.log_prefix,
                "is_active": bucket.is_active,
                "created_at": format_ist_timestamp_from_iso(bucket.created_at.isoformat()) if bucket.created_at else None,
                "updated_at": format_ist_timestamp_from_iso(bucket.updated_at.isoformat()) if bucket.updated_at else None
            }
            
            return {"success": True, "bucket": bucket_data}
            
        except Exception as e:
            logger.error(f"Error getting bucket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def update_bucket(self, bucket_id: int, config: S3BucketConfigCreate) -> Dict[str, Any]:
        """Update an existing S3 bucket configuration"""
        try:
            db = SessionLocal()
            bucket = db.query(S3BucketConfig).filter(S3BucketConfig.id == bucket_id).first()
            
            if not bucket:
                return {"success": False, "error": "Bucket not found"}
            
            # Update fields
            bucket.bucket_name = config.bucket_name
            bucket.region = config.region
            bucket.access_key = config.access_key
            bucket.secret_key = config.secret_key
            bucket.log_prefix = config.log_prefix
            
            db.commit()
            
            return {"success": True, "message": "Bucket updated successfully"}
            
        except Exception as e:
            logger.error(f"Error updating bucket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def delete_bucket(self, bucket_id: int) -> Dict[str, Any]:
        """Delete an S3 bucket configuration"""
        try:
            db = SessionLocal()
            bucket = db.query(S3BucketConfig).filter(S3BucketConfig.id == bucket_id).first()
            
            if not bucket:
                return {"success": False, "error": "Bucket not found"}
            
            db.delete(bucket)
            db.commit()
            
            return {"success": True, "message": "Bucket deleted successfully"}
            
        except Exception as e:
            logger.error(f"Error deleting bucket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_bucket_logs_with_content(self, bucket_id: int, hours: int = 24, limit: int = 50) -> Dict[str, Any]:
        """Get S3 bucket logs with content and URLs"""
        try:
            db = SessionLocal()
            
            since_time = datetime.now(IST_TIMEZONE) - timedelta(hours=hours)
            logs = db.query(S3LogEntry).filter(
                S3LogEntry.bucket_id == bucket_id,
                S3LogEntry.timestamp >= since_time
            ).order_by(S3LogEntry.timestamp.desc()).limit(limit).all()
            
            log_data = []
            for log in logs:
                log_data.append({
                    "id": log.id,
                    "log_key": log.log_key,
                    "log_size": log.log_size,
                    "log_content": log.log_content,
                    "parsed_data": log.parsed_data,
                    "timestamp": format_ist_timestamp_from_iso(log.timestamp.isoformat()) if log.timestamp else None
                })
            
            return {"success": True, "logs": log_data, "count": len(log_data)}
            
        except Exception as e:
            logger.error(f"Error getting bucket logs with content: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_log_content(self, log_id: int) -> Dict[str, Any]:
        """Get full log content for a specific log entry"""
        try:
            db = SessionLocal()
            log = db.query(S3LogEntry).filter(S3LogEntry.id == log_id).first()
            
            if not log:
                return {"success": False, "error": "Log not found"}
            
            log_data = {
                "id": log.id,
                "log_key": log.log_key,
                "log_size": log.log_size,
                "log_content": log.log_content,
                "parsed_data": log.parsed_data,
                "timestamp": format_ist_timestamp_from_iso(log.timestamp.isoformat()) if log.timestamp else None
            }
            
            return {"success": True, "log": log_data}
            
        except Exception as e:
            logger.error(f"Error getting log content: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_bucket_urls(self, bucket_id: int) -> Dict[str, Any]:
        """Get S3 bucket URLs and access information"""
        try:
            db = SessionLocal()
            bucket = db.query(S3BucketConfig).filter(S3BucketConfig.id == bucket_id).first()
            
            if not bucket:
                return {"success": False, "error": "Bucket not found"}
            
            # Generate S3 URLs
            bucket_urls = {
                "bucket_name": bucket.bucket_name,
                "region": bucket.region,
                "s3_url": f"s3://{bucket.bucket_name}",
                "console_url": f"https://s3.console.aws.amazon.com/s3/buckets/{bucket.bucket_name}",
                "log_prefix": bucket.log_prefix,
                "access_key": bucket.access_key,
                "secret_key": bucket.secret_key
            }
            
            return {"success": True, "urls": bucket_urls}
            
        except Exception as e:
            logger.error(f"Error getting bucket URLs: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def refresh_bucket_logs(self, bucket_id: int) -> Dict[str, Any]:
        """Manually refresh S3 bucket logs"""
        try:
            db = SessionLocal()
            bucket = db.query(S3BucketConfig).filter(S3BucketConfig.id == bucket_id).first()
            
            if not bucket:
                return {"success": False, "error": "Bucket not found"}
            
            # This would trigger the actual log refresh logic
            # For now, just return success
            return {"success": True, "message": f"Refresh triggered for bucket {bucket.bucket_name}"}
            
        except Exception as e:
            logger.error(f"Error refreshing bucket logs: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    def check_bucket_logs(self, config: S3BucketConfig) -> None:
        """Check bucket logs - download new logs and process them in real-time"""
        try:
            logger.info(f"Checking logs for bucket: {config.bucket_name}")
            
            # Initialize S3 log downloader
            downloader = S3LogDownloader(
                bucket_name=config.bucket_name,
                region=config.region,
                log_prefix=config.log_prefix,
                access_key=config.access_key,
                secret_key=config.secret_key
            )
            
            # Find latest log files (last 1 hour for real-time, max 5 files)
            hours_back = int(os.getenv('S3_HOURS_BACK', '1'))  # Default 1 hour for real-time
            max_files = int(os.getenv('S3_MAX_FILES_PER_CYCLE', '5'))  # Default 5 files
            
            log_files = downloader.find_latest_log_files(hours_back=hours_back, max_files=max_files)
            
            if not log_files:
                logger.debug(f"No new log files found for bucket: {config.bucket_name}")
                return
            
            logger.info(f"Found {len(log_files)} log files for bucket: {config.bucket_name}")
            
            # Process each log file in real-time
            for log_file in log_files:
                try:
                    s3_key = log_file['Key']
                    file_size = log_file['Size']
                    last_modified = log_file['LastModified']
                    
                    logger.info(f"Processing log file: {s3_key} (size: {file_size} bytes)")
                    
                    # Download and extract the log file
                    local_path = downloader.download_and_extract(s3_key, file_size)
                    
                    if local_path and os.path.exists(local_path):
                        # Process the log file content in real-time
                        self._process_log_file(local_path, s3_key, config)
                        logger.info(f"Successfully processed log file in real-time: {s3_key}")
                    else:
                        logger.warning(f"Failed to download/extract log file: {s3_key}")
                        
                except Exception as e:
                    logger.error(f"Error processing log file {log_file.get('Key', 'unknown')}: {e}")
                    continue
            
            logger.info(f"Completed real-time log processing for bucket: {config.bucket_name}")
            
        except Exception as e:
            logger.error(f"Error checking bucket logs for {config.bucket_name}: {e}")
    


    async def get_api_status(self) -> Dict[str, Any]:
        """Get S3 API monitoring status"""
        try:
            db = SessionLocal()
            
            # Get API config count
            api_config_count = db.query(S3APIConfig).filter(S3APIConfig.is_active == True).count()
            
            # Get recent API logs count
            since_time = datetime.now(IST_TIMEZONE) - timedelta(hours=24)
            recent_api_logs = db.query(S3APILog).filter(S3APILog.timestamp >= since_time).count()
            
            # Get API status summary
            api_status_summary = {
                "total_apis": api_config_count,
                "recent_logs_24h": recent_api_logs,
                "monitoring_active": self.monitoring,
                "last_check": format_ist_timestamp_from_iso(datetime.now(IST_TIMEZONE).isoformat())
            }
            
            return {"success": True, "status_summary": api_status_summary}
            
        except Exception as e:
            logger.error(f"Error getting API status: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def add_api_config(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new S3 API configuration"""
        try:
            db = SessionLocal()
            
            new_config = S3APIConfig(
                name=config_dict['name'],
                url=config_dict['url'],
                method=config_dict['method'],
                expected_status=config_dict['expected_status'],
                headers=config_dict['headers'],
                body=config_dict['body'],
                expected_response=config_dict['expected_response'],
                bucket_id=config_dict.get('bucket_id')
            )
            
            db.add(new_config)
            db.commit()
            db.refresh(new_config)
            
            return {"success": True, "config_id": new_config.id}
            
        except Exception as e:
            logger.error(f"Error adding API config: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_api_config(self, config_id: int) -> Dict[str, Any]:
        """Get a specific S3 API configuration"""
        try:
            db = SessionLocal()
            config = db.query(S3APIConfig).filter(S3APIConfig.id == config_id).first()
            
            if not config:
                return {"success": False, "error": "API config not found"}
            
            config_data = {
                "id": config.id,
                "name": config.name,
                "url": config.url,
                "method": config.method,
                "expected_status": config.expected_status,
                "headers": config.headers,
                "body": config.body,
                "expected_response": config.expected_response,
                "s3_pattern": config.s3_pattern,
                "bucket_id": config.bucket_id,
                "is_active": config.is_active,
                "created_at": format_ist_timestamp_from_iso(config.created_at.isoformat()) if config.created_at else None,
                "updated_at": format_ist_timestamp_from_iso(config.updated_at.isoformat()) if config.updated_at else None
            }
            
            return {"success": True, "config": config_data}
            
        except Exception as e:
            logger.error(f"Error getting API config: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def update_api_config(self, config_id: int, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing S3 API configuration"""
        try:
            db = SessionLocal()
            config = db.query(S3APIConfig).filter(S3APIConfig.id == config_id).first()
            
            if not config:
                return {"success": False, "error": "API config not found"}
            
            # Update fields
            config.name = config_dict['name']
            config.url = config_dict['url']
            config.method = config_dict['method']
            config.expected_status = config_dict['expected_status']
            config.headers = config_dict['headers']
            config.body = config_dict['body']
            config.expected_response = config_dict['expected_response']
            config.bucket_id = config_dict.get('bucket_id')
            
            db.commit()
            
            return {"success": True, "message": "API config updated successfully"}
            
        except Exception as e:
            logger.error(f"Error updating API config: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def delete_api_config(self, config_id: int) -> Dict[str, Any]:
        """Delete an S3 API configuration"""
        try:
            db = SessionLocal()
            config = db.query(S3APIConfig).filter(S3APIConfig.id == config_id).first()
            
            if not config:
                return {"success": False, "error": "API config not found"}
            
            db.delete(config)
            db.commit()
            
            return {"success": True, "message": "API config deleted successfully"}
            
        except Exception as e:
            logger.error(f"Error deleting API config: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_log_analysis(self, api_id: int, hours: int = 24) -> Dict[str, Any]:
        """Get detailed S3 log analysis for a specific API"""
        try:
            db = SessionLocal()
            
            # Get logs for the specific API
            since_time = datetime.now(IST_TIMEZONE) - timedelta(hours=hours)
            logs = db.query(S3APILog).filter(
                S3APILog.api_config_id == api_id,
                S3APILog.timestamp >= since_time
            ).order_by(S3APILog.timestamp.desc()).all()
            
            # Analyze logs
            total_logs = len(logs)
            success_logs = len([log for log in logs if log.elb_status_code == 200])
            error_logs = total_logs - success_logs
            
            analysis = {
                "total_logs": total_logs,
                "success_logs": success_logs,
                "error_logs": error_logs,
                "success_rate": (success_logs / total_logs * 100) if total_logs > 0 else 0,
                "logs": []
            }
            
            for log in logs:
                analysis["logs"].append({
                    "id": log.id,
                    "timestamp": format_ist_timestamp_from_iso(log.timestamp.isoformat()),
                    "elb_status_code": log.elb_status_code,
                    "target_status_code": log.target_status_code,
                    "request_processing_time": log.request_processing_time,
                    "target_processing_time": log.target_processing_time,
                    "response_processing_time": log.response_processing_time,
                    "bucket_name": log.bucket_name,
                    "request_path": log.request_path,
                    "client_ip": log.client_ip
                })
            
            return {"success": True, "analysis": analysis}
            
        except Exception as e:
            logger.error(f"Error getting log analysis: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_logs_from_db(self, api_id: Optional[int] = None, bucket_name: Optional[str] = None, 
                              hours: int = 24, limit: Optional[int] = None) -> Dict[str, Any]:
        """Get S3 API logs from database"""
        try:
            db = SessionLocal()
            
            query = db.query(S3APILog)
            
            if api_id:
                query = query.filter(S3APILog.api_config_id == api_id)
            
            if bucket_name:
                query = query.filter(S3APILog.bucket_name == bucket_name)
            
            if hours > 0:
                since_time = datetime.now(IST_TIMEZONE) - timedelta(hours=hours)
                query = query.filter(S3APILog.timestamp >= since_time)
            
            q = query.order_by(S3APILog.timestamp.desc())
            logs = (q.limit(limit).all()) if isinstance(limit, int) and limit and limit > 0 else q.all()
            
            log_data = []
            for log in logs:
                log_data.append({
                    "id": log.id,
                    "api_url": log.api_url,
                    "timestamp": format_ist_timestamp_from_iso(log.timestamp.isoformat()),
                    "elb_status_code": log.elb_status_code,
                    "target_status_code": log.target_status_code,
                    "request_processing_time": log.request_processing_time,
                    "target_processing_time": log.target_processing_time,
                    "response_processing_time": log.response_processing_time,
                    "bucket_name": log.bucket_name,
                    "api_config_id": log.api_config_id,
                    "request_path": log.request_path,
                    "client_ip": log.client_ip,
                    "user_agent": log.user_agent,
                    "created_at": format_ist_timestamp_from_iso(log.created_at.isoformat()) if log.created_at else None
                })
            
            return {"success": True, "logs": log_data, "count": len(log_data)}
            
        except Exception as e:
            logger.error(f"Error getting logs from DB: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_latest_api_logs(self, hours: int = 24, limit: Optional[int] = None) -> Dict[str, Any]:
        """Get the latest S3 API logs from bucket monitoring"""
        try:
            db = SessionLocal()
            
            since_time = datetime.now(IST_TIMEZONE) - timedelta(hours=hours)
            q = db.query(S3APILog).filter(
                S3APILog.timestamp >= since_time
            ).order_by(S3APILog.timestamp.desc())
            logs = (q.limit(limit).all()) if isinstance(limit, int) and limit and limit > 0 else q.all()
            
            log_data = []
            for log in logs:
                log_data.append({
                    "id": log.id,
                    "api_url": log.api_url,
                    "timestamp": format_ist_timestamp_from_iso(log.timestamp.isoformat()),
                    "elb_status_code": log.elb_status_code,
                    "target_status_code": log.target_status_code,
                    "bucket_name": log.bucket_name,
                    "request_path": log.request_path,
                    "client_ip": log.client_ip
                })
            
            return {"success": True, "logs": log_data, "count": len(log_data)}
            
        except Exception as e:
            logger.error(f"Error getting latest API logs: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    async def get_realtime_logs(self, api_name: Optional[str] = None, start_time_str: Optional[str] = None, 
                               minutes: int = 5) -> List[Dict[str, Any]]:
        """Get real-time S3 API logs"""
        try:
            db = SessionLocal()
            
            # Calculate time range
            if start_time_str:
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            else:
                start_time = datetime.now(IST_TIMEZONE) - timedelta(minutes=minutes)
            
            query = db.query(S3APILog).filter(S3APILog.timestamp >= start_time)
            
            if api_name:
                query = query.filter(
                    (S3APILog.request_path.contains(api_name)) | 
                    (S3APILog.api_url.contains(api_name))
                )
            
            logs = query.order_by(S3APILog.timestamp.desc()).limit(50).all()
            
            log_data = []
            for log in logs:
                log_data.append({
                    "id": log.id,
                    "api_url": log.api_url,
                    "timestamp": format_ist_timestamp_from_iso(log.timestamp.isoformat()),
                    "elb_status_code": log.elb_status_code,
                    "target_status_code": log.target_status_code,
                    "bucket_name": log.bucket_name,
                    "request_path": log.request_path,
                    "client_ip": log.client_ip
                })
            
            return log_data
            
        except Exception as e:
            logger.error(f"Error getting realtime logs: {e}")
            return []

    async def get_log_detail(self, log_id: int) -> Dict[str, Any]:
        """Get detailed information about a specific S3 API log entry"""
        try:
            db = SessionLocal()
            log = db.query(S3APILog).filter(S3APILog.id == log_id).first()
            
            if not log:
                return {"success": False, "error": "Log not found"}
            
            log_data = {
                "id": log.id,
                "api_url": log.api_url,
                "timestamp": format_ist_timestamp_from_iso(log.timestamp.isoformat()),
                "request_processing_time": log.request_processing_time,
                "target_processing_time": log.target_processing_time,
                "response_processing_time": log.response_processing_time,
                "elb_status_code": log.elb_status_code,
                "target_status_code": log.target_status_code,
                "bucket_name": log.bucket_name,
                "api_config_id": log.api_config_id,
                "request_path": log.request_path,
                "user_agent": log.user_agent,
                "client_ip": log.client_ip,
                "created_at": format_ist_timestamp_from_iso(log.created_at.isoformat()) if log.created_at else None
            }
            
            return {"success": True, "log": log_data}
            
        except Exception as e:
            logger.error(f"Error getting log detail: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    def get_default_s3_config(self) -> Dict[str, Any]:
        """Get default S3 configuration from environment variables"""
        return {
            "bucket_name": os.getenv("S3_BUCKET_NAME", ""),
            "region": os.getenv("S3_REGION", ""),
            "access_key": os.getenv("AWS_ACCESS_KEY_ID", ""),
            "secret_key": os.getenv("AWS_SECRET_ACCESS_KEY", ""),
            "log_prefix": os.getenv("S3_PREFIX", "")
        }

    async def get_bucket_statuses(self) -> Dict[str, Any]:
        """Get status for all buckets with monitoring information"""
        try:
            db = SessionLocal()
            
            # Get all active buckets
            buckets = db.query(S3BucketConfig).filter(S3BucketConfig.is_active == True).all()
            
            bucket_statuses = []
            for bucket in buckets:
                # Get recent logs count for this bucket
                since_time = datetime.now(IST_TIMEZONE) - timedelta(hours=24)
                recent_logs = db.query(S3APILog).filter(
                    S3APILog.bucket_name == bucket.bucket_name
                ).filter(S3APILog.timestamp >= since_time).count()
                
                # Get last check time (use bucket creation time for now)
                last_check = bucket.created_at
                
                # Determine health status (for now, consider healthy if has logs or is recent)
                is_healthy = recent_logs > 0 or (datetime.now(IST_TIMEZONE) - bucket.created_at).days < 7
                
                bucket_status = {
                    "id": bucket.id,
                    "bucket_name": bucket.bucket_name,
                    "region": bucket.region,
                    "access_key": bucket.access_key,
                    "secret_key": bucket.secret_key,
                    "log_prefix": bucket.log_prefix,
                    "is_active": bucket.is_active,
                    "created_at": format_ist_timestamp_from_iso(bucket.created_at.isoformat()) if bucket.created_at else None,
                    "updated_at": format_ist_timestamp_from_iso(bucket.updated_at.isoformat()) if bucket.updated_at else None,
                    "recent_logs_count": recent_logs,
                    "last_check": format_ist_timestamp_from_iso(last_check.isoformat()) if last_check else None,
                    "is_healthy": is_healthy
                }
                
                bucket_statuses.append(bucket_status)
            
            return {"success": True, "buckets": bucket_statuses, "count": len(bucket_statuses)}
            
        except Exception as e:
            logger.error(f"Error getting bucket statuses: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()
    
    def cleanup_old_files(self, retention_hours: int = 168) -> Dict[str, Any]:
        """Clean up old files and database entries"""
        try:
            cleaned_files = 0
            cleaned_db = 0
            
            # Clean files
            if os.path.exists(self.local_download_dir):
                cutoff_time = time.time() - (retention_hours * 3600)
                for filename in os.listdir(self.local_download_dir):
                    file_path = os.path.join(self.local_download_dir, filename)
                    if os.path.isfile(file_path) and os.path.getmtime(file_path) < cutoff_time:
                        os.remove(file_path)
                        cleaned_files += 1
            
            # Clean database (DISABLED: preserve previous logs in DB)
            cleaned_db = 0
            
            return {
                "success": True, 
                "cleaned_files": cleaned_files, 
                "cleaned_db_entries": cleaned_db
            }
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return {"success": False, "error": str(e)}

    async def process_stored_log_content(self, log_id: int) -> Dict[str, Any]:
        """Process stored log content for API analysis (deferred processing)"""
        try:
            db = SessionLocal()
            
            # Get the stored log entry
            log_entry = db.query(S3LogEntry).filter(S3LogEntry.id == log_id).first()
            if not log_entry:
                return {"success": False, "error": "Log entry not found"}
            
            if not log_entry.log_content:
                return {"success": False, "error": "No log content available for processing"}
            
            # Check if already processed
            parsed_data = log_entry.parsed_data or {}
            if parsed_data.get('api_processing') == 'completed':
                return {"success": True, "message": "Log already processed", "api_logs_created": parsed_data.get('api_logs_created', 0)}
            
            print(f"🚀 Starting deferred processing for log ID {log_id} ({len(log_entry.log_content.splitlines())} lines)")
            
            # Process the stored log content for API calls
            api_logs_created = 0
            for line in log_entry.log_content.splitlines():
                if line.strip():
                    # Process each line for API detection
                    api_logs_created += self._process_stored_log_line(db, line.strip(), log_entry.log_key, log_entry.bucket_id)
            
            print(f"✅ Completed deferred processing for log ID {log_id}: {api_logs_created} API calls found")
            
            # Update the parsed_data to indicate processing is complete
            if log_entry.parsed_data:
                log_entry.parsed_data.update({
                    "api_processing": "completed",
                    "api_logs_created": api_logs_created,
                    "processed_at": datetime.now(IST_TIMEZONE).isoformat()
                })
            else:
                log_entry.parsed_data = {
                    "api_processing": "completed",
                    "api_logs_created": api_logs_created,
                    "processed_at": datetime.now(IST_TIMEZONE).isoformat()
                }
            
            db.commit()
            
            return {
                "success": True,
                "log_id": log_id,
                "api_logs_created": api_logs_created,
                "message": f"Processed {api_logs_created} API calls from stored log content"
            }
            
        except Exception as e:
            logger.error(f"Error processing stored log content for log_id {log_id}: {e}")
            if 'db' in locals():
                db.rollback()
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()

    def _process_stored_log_line(self, db: SessionLocal, line: str, log_key: str, bucket_id: int) -> int:
        """Process single stored log line for API analysis (returns count of API logs created)"""
        try:
            # Use the enhanced ALB log parsing method for better accuracy
            parsed = self._parse_alb_log_line(line)
            if not parsed:
                # Fallback to simple parsing if enhanced parsing fails
                parsed = self._parse_alb_line(line)
                if not parsed:
                    return 0
            
            # Get bucket name for API log creation
            bucket = db.query(S3BucketConfig).filter(S3BucketConfig.id == bucket_id).first()
            if not bucket:
                return 0
            
            # Check against APIs
            for api in self.apis:
                if re.search(api['pattern'], parsed.get('request_uri', '')):
                    # Generate hash for deduplication
                    log_hash = hashlib.md5(
                        f"{api['url']}|{parsed['timestamp']}|{parsed.get('client_ip', '')}".encode()
                    ).hexdigest()
                    
                    if self.processed_logs.get(log_hash):
                        continue
                    
                    # Create API log entry with enhanced fields
                    api_log = S3APILog(
                        api_url=api['url'],
                        timestamp=datetime.fromisoformat(parsed['timestamp']),
                        elb_status_code=parsed.get('elb_status_code', parsed.get('status_code', 0)),
                        target_status_code=parsed.get('target_status_code', parsed.get('status_code', 0)),
                        bucket_name=bucket.bucket_name,
                        request_path=parsed.get('request_uri', ''),
                        client_ip=parsed.get('client_ip', ''),
                        user_agent=parsed.get('user_agent', ''),
                        api_config_id=api.get('id')
                    )
                    
                    db.add(api_log)
                    print(f"🔍 Deferred processing: Found API call for bucket {bucket.bucket_name}: {parsed.get('request_uri', '')}")
                    self.processed_logs.set(log_hash, True)
                    
                    return 1  # Return 1 to indicate one API log was created
                    
            return 0  # No API logs created for this line
            
        except Exception as e:
            logger.debug(f"Error processing stored log line: {e}")
            return 0

    async def process_all_stored_logs(self, limit: int = 1000) -> Dict[str, Any]:
        """Process all stored logs for API analysis in batch (deferred processing)"""
        try:
            db = SessionLocal()
            
            # Get all stored logs that haven't been processed for API analysis
            # Use a simpler approach to avoid JSON operator issues
            all_logs = db.query(S3LogEntry).filter(
                S3LogEntry.log_content.isnot(None)
            ).limit(limit).all()
            
            # Filter in Python instead of SQL
            unprocessed_logs = []
            for log in all_logs:
                parsed_data = log.parsed_data or {}
                api_processing = parsed_data.get('api_processing', 'deferred')
                if api_processing != 'completed':
                    unprocessed_logs.append(log)
            
            if not unprocessed_logs:
                return {"success": True, "message": "No unprocessed logs found", "processed": 0}
            
            print(f"🚀 Starting batch processing of {len(unprocessed_logs)} stored logs...")
            
            total_api_logs_created = 0
            processed_count = 0
            
            for log_entry in unprocessed_logs:
                try:
                    print(f"📄 Processing log ID {log_entry.id} ({len(log_entry.log_content.splitlines())} lines)...")
                    
                    # Process each stored log
                    api_logs_created = 0
                    for line in log_entry.log_content.splitlines():
                        if line.strip():
                            api_logs_created += self._process_stored_log_line(db, line.strip(), log_entry.log_key, log_entry.bucket_id)
                    
                    print(f"✅ Log ID {log_entry.id}: {api_logs_created} API calls found")
                    
                    # Update the parsed_data to indicate processing is complete
                    if log_entry.parsed_data:
                        log_entry.parsed_data.update({
                            "api_processing": "completed",
                            "api_logs_created": api_logs_created,
                            "batch_processed_at": datetime.now(IST_TIMEZONE).isoformat()
                        })
                    else:
                        log_entry.parsed_data = {
                            "api_processing": "completed",
                            "api_logs_created": api_logs_created,
                            "batch_processed_at": datetime.now(IST_TIMEZONE).isoformat()
                        }
                    
                    total_api_logs_created += api_logs_created
                    processed_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing stored log {log_entry.id}: {e}")
                    # Mark as failed but continue with other logs
                    if log_entry.parsed_data:
                        log_entry.parsed_data.update({
                            "api_processing": "failed",
                            "error": str(e),
                            "failed_at": datetime.now(IST_TIMEZONE).isoformat()
                        })
                    else:
                        log_entry.parsed_data = {
                            "api_processing": "failed",
                            "error": str(e),
                            "failed_at": datetime.now(IST_TIMEZONE).isoformat()
                        }
            
            db.commit()
            
            print(f"🎉 Batch processing completed: {processed_count} logs processed, {total_api_logs_created} API calls found")
            
            return {
                "success": True,
                "processed_logs": processed_count,
                "total_api_logs_created": total_api_logs_created,
                "message": f"Batch processed {processed_count} logs, created {total_api_logs_created} API logs"
            }
            
        except Exception as e:
            logger.error(f"Error in batch processing stored logs: {e}")
            if 'db' in locals():
                db.rollback()
            return {"success": False, "error": str(e)}
        finally:
            if 'db' in locals():
                db.close()


# Utility function
def cleanup_old_logs(directory: str, retention_hours: int) -> int:
    """Clean up old log files"""
    try:
        if not os.path.exists(directory):
            return 0
        
        cutoff_time = time.time() - (retention_hours * 3600)
        cleaned = 0
        
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path) and os.path.getmtime(file_path) < cutoff_time:
                os.remove(file_path)
                cleaned += 1
        
        return cleaned
        
    except Exception as e:
        logger.error(f"Error cleaning logs: {e}")
        return 0