# 🚀 Integrated Monitor - Comprehensive API Monitoring System

A powerful, production-ready monitoring system that provides real-time API health monitoring, S3 bucket analysis, and beautiful Grafana dashboards.

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [Grafana Dashboard](#grafana-dashboard)
- [Configuration](#configuration)
- [Docker Deployment](#docker-deployment)
- [Development](#development)
- [Project Structure](#project-structure)

---

## 🎯 Overview

The Integrated Monitor is a comprehensive monitoring solution designed for modern applications. It provides real-time monitoring of API endpoints, S3 bucket health, and automated log analysis with beautiful visualizations through Grafana.

### Key Capabilities

- **🔍 Real-time API Monitoring**: Continuous health checks with configurable intervals
- **☁️ S3 Bucket Monitoring**: AWS S3 bucket health and log analysis
- **📊 S3 API Monitoring**: API health monitoring through S3 log analysis
- **🧪 Manual Testing**: On-demand API testing with detailed results
- **📈 Grafana Integration**: Beautiful dashboards with real-time metrics
- **🚨 Alerting**: Configurable alerts for monitoring failures
- **🔧 Complete REST API**: Full CRUD operations for all monitoring configurations

---

## ✨ Features

### Core Monitoring
- **Heartbeat Monitoring**: Automated health checks for API endpoints with email alerts
- **S3 Bucket Monitoring**: Real-time S3 bucket health and access monitoring
- **S3 API Monitoring**: API health analysis through S3 access logs with automatic log parsing and storage
- **Manual Testing**: On-demand API testing with detailed response analysis

### Visualization & Analytics
- **Grafana Dashboards**: Pre-configured dashboards with real-time metrics
- **Prometheus Integration**: Metrics collection and storage
- **Custom Metrics**: Application-specific monitoring metrics
- **Historical Data**: Trend analysis and performance tracking

### API & Integration
- **RESTful API**: Complete CRUD operations for all configurations
- **Swagger Documentation**: Interactive API documentation
- **Web Dashboard**: User-friendly web interface
- **Docker Support**: Containerized deployment

---

## ⚡ Quick Start

### Prerequisites
- Python 3.8+
- Docker and Docker Compose (for containerized deployment)
- AWS credentials (for S3 monitoring)

### 1. Clone and Setup
```bash
git clone <repository-url>
cd integrated_monitor
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.example .env
# Edit .env with your configuration
```

### 4. Start the Application
```bash
# Option 1: Direct Python execution
python3 main.py

# Option 2: Docker Compose (recommended)
docker-compose up -d
```

### 5. Test Email Configuration (Optional)
```bash
python3 test_email_service.py
```

### 6. Test S3 API Logs (Optional)
```bash
python3 test_s3_api_logs.py
```

### 7. Access the Application
- **Web Dashboard**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **Grafana**: http://localhost:3000 (admin/admin)

---

## 🛠 Installation

### Manual Installation

1. **Install Python Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up Environment Variables**
   ```bash
   # Create .env file
   cat > .env << EOF
   DATABASE_URL=sqlite:///./monitor.db
   AWS_ACCESS_KEY_ID=your_access_key
   AWS_SECRET_ACCESS_KEY=your_secret_key
   AWS_DEFAULT_REGION=us-east-1
   GRAFANA_URL=http://localhost:3000
   GRAFANA_USERNAME=admin
   GRAFANA_PASSWORD=admin
   
   # Email Configuration (for heartbeat alerts)
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=your_email@gmail.com
   SMTP_PASSWORD=your_app_password
   SENDER_EMAIL=your_email@gmail.com
   SENDER_NAME=Integrated Monitor
   DEFAULT_EMAIL_RECIPIENTS=admin@company.com,ops@company.com
   EOF
   ```

3. **Initialize Database**
   ```bash
   python3 -c "from database import engine, Base; Base.metadata.create_all(bind=engine)"
   ```

### Docker Installation

1. **Build and Start Services**
   ```bash
   docker-compose up -d
   ```

2. **Verify Services**
   ```bash
   docker-compose ps
   ```

3. **View Logs**
   ```bash
   docker-compose logs -f integrated-monitor
   ```

---

## 📖 Usage

### Web Dashboard

The web dashboard provides a user-friendly interface for:
- Viewing monitoring status
- Adding new monitoring configurations
- Viewing historical data
- Running manual tests

Access at: http://localhost:8000

### API Usage

#### Add a Heartbeat Monitor
```bash
curl -X POST "http://localhost:8000/api/heartbeat/add" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My API",
    "url": "https://api.example.com/health",
    "method": "GET",
    "interval_minutes": 5,
    "timeout_seconds": 30,
    "expected_status": 200
  }'
```

#### Add S3 Bucket Monitor
```bash
curl -X POST "http://localhost:8000/api/s3/add" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My S3 Bucket",
    "bucket_name": "my-bucket",
    "region": "us-east-1",
    "check_interval_minutes": 10
  }'
```

#### Run Manual Test
```bash
curl -X POST "http://localhost:8000/api/manual/test" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://api.example.com/test",
    "method": "POST",
    "headers": {"Authorization": "Bearer token"},
    "body": "{\"test\": \"data\"}"
  }'
```

### Configuration Management

All monitoring configurations support full CRUD operations:
- **Create**: Add new monitoring configurations
- **Read**: Retrieve configurations and status
- **Update**: Modify existing configurations
- **Delete**: Remove monitoring configurations

### Email Alerts Configuration

The heartbeat monitoring system automatically sends email alerts when:
- **Status Code ≠ 200**: Any non-200 HTTP response triggers an alert
- **Recovery Detection**: When a previously failing endpoint recovers
- **Manual Test Failures**: Failed manual tests also trigger alerts

#### Email Setup for Gmail:
1. **Enable 2-Factor Authentication** on your Google account
2. **Generate App Password**:
   - Go to Google Account settings > Security > App passwords
   - Select "Mail" and generate a new password
   - Use this password in `SMTP_PASSWORD`
3. **Configure Environment Variables**:
   ```bash
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=your_email@gmail.com
   SMTP_PASSWORD=your_app_password
   SENDER_EMAIL=your_email@gmail.com
   DEFAULT_EMAIL_RECIPIENTS=admin@company.com,ops@company.com
   ```

---

## 📚 API Documentation

### Interactive Documentation
- **Swagger UI**: http://localhost:8000/docs
- **OpenAPI Schema**: http://localhost:8000/openapi.json

### API Categories

#### Health & Status
- `GET /health` - Service health check
- `GET /api/stats` - System statistics

#### Heartbeat Monitoring
- `POST /api/heartbeat/add` - Add endpoint
- `GET /api/heartbeat/endpoints` - List endpoints
- `GET /api/heartbeat/status` - Get status
- `PUT /api/heartbeat/update/{id}` - Update endpoint
- `DELETE /api/heartbeat/delete/{id}` - Delete endpoint
- `GET /api/heartbeat/history/{id}` - Get history
- `POST /api/heartbeat/test/{id}` - Test endpoint

#### Email Alerts
- `GET /api/email/status` - Get email service status
- `POST /api/email/test` - Test email configuration

#### S3 Bucket Monitoring
- `POST /api/s3/add` - Add bucket
- `GET /api/s3/buckets` - List buckets
- `GET /api/s3/status` - Get status
- `PUT /api/s3/update/{id}` - Update bucket
- `DELETE /api/s3/delete/{id}` - Delete bucket
- `GET /api/s3/logs/{id}` - Get logs
- `POST /api/s3/refresh/{id}` - Refresh logs

#### S3 API Monitoring
- `POST /api/s3/api/add` - Add API config
- `GET /api/s3/api/configs` - List configs
- `GET /api/s3/api/status` - Get status
- `PUT /api/s3/api/update/{id}` - Update config
- `DELETE /api/s3/api/delete/{id}` - Delete config
- `GET /api/s3/api/logs` - Get logs
- `GET /api/s3/api/latest-logs` - Get latest parsed logs from S3 monitoring
- `GET /api/s3/api/log-analysis/{id}` - Get analysis
- `POST /api/s3/api/refresh-logs/{bucket_id}` - Refresh S3 API logs for a bucket

#### Manual Testing
- `POST /api/manual/endpoints` - Add endpoint
- `GET /api/manual/endpoints` - List endpoints
- `POST /api/manual/test` - Run test
- `GET /api/manual/results` - Get results

#### Grafana Integration
- `POST /api/grafana/setup` - Setup dashboard
- `GET /api/grafana/status` - Get status

For detailed API documentation, see [API_ENDPOINTS_README.md](API_ENDPOINTS_README.md)

---

## 📊 Grafana Dashboard

### Setup
The Grafana dashboard is automatically configured when using Docker Compose. For manual setup:

1. **Start Grafana**
   ```bash
   docker run -d -p 3000:3000 grafana/grafana
   ```

2. **Configure Data Source**
   - Access Grafana at http://localhost:3000
   - Login with admin/admin
   - Add Prometheus data source: http://prometheus:9090

3. **Import Dashboard**
   - Import the dashboard from `grafana/dashboards/api_monitor_dashboard.json`

### Dashboard Features
- **Real-time Metrics**: Live monitoring data
- **Historical Trends**: Performance over time
- **Alert Status**: Current alert conditions
- **Service Health**: Overall system status

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite:///./monitor.db` |
| `AWS_ACCESS_KEY_ID` | AWS access key for S3 monitoring | - |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key for S3 monitoring | - |
| `AWS_DEFAULT_REGION` | AWS region | `us-east-1` |
| `GRAFANA_URL` | Grafana server URL | `http://localhost:3000` |
| `GRAFANA_USERNAME` | Grafana username | `admin` |
| `GRAFANA_PASSWORD` | Grafana password | `admin` |
| `SMTP_SERVER` | SMTP server for email alerts | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port for email alerts | `587` |
| `SMTP_USERNAME` | SMTP username for email alerts | - |
| `SMTP_PASSWORD` | SMTP password/app password for email alerts | - |
| `SENDER_EMAIL` | Sender email address for alerts | - |
| `SENDER_NAME` | Sender name for alerts | `Integrated Monitor` |
| `DEFAULT_EMAIL_RECIPIENTS` | Comma-separated list of alert recipients | - |

### Timezone Configuration

All timestamps in the application are displayed in **Indian Standard Time (IST)** (UTC+5:30). This includes:
- API response timestamps
- Database timestamps
- Log timestamps
- Dashboard timestamps

### Monitoring Configuration

#### Heartbeat Monitoring
- **Interval**: 1-60 minutes
- **Timeout**: 5-300 seconds
- **Expected Status**: HTTP status codes
- **Headers**: Custom request headers
- **Email Alerts**: Automatic notifications when status ≠ 200
- **Recovery Notifications**: Alerts when endpoints recover from failures

#### S3 Monitoring
- **Bucket Name**: AWS S3 bucket name
- **Region**: AWS region
- **Check Interval**: 5-60 minutes
- **Log Analysis**: Access log monitoring
- **Automatic Log Parsing**: Downloads and parses ALB logs from S3
- **API Log Storage**: Stores parsed logs in S3APILog table for analysis
- **Configuration Linking**: Automatically links logs with API configurations

---

## 🐳 Docker Deployment

### Production Deployment

1. **Create Production Configuration**
   ```bash
   # Create production .env
   cp .env.example .env.prod
   # Edit with production values
   ```

2. **Deploy with Docker Compose**
   ```bash
   docker-compose -f docker-compose.yml --env-file .env.prod up -d
   ```

3. **Scale Services**
   ```bash
   docker-compose up -d --scale integrated-monitor=3
   ```

### Docker Services

- **integrated-monitor**: Main application (port 8000)
- **api-metrics-exporter**: Prometheus metrics (port 9092)
- **prometheus**: Metrics collection (port 9091)
- **grafana**: Dashboard (port 3000)
- **alertmanager**: Alert notifications (port 9093)

---

## 🔧 Development

### Project Structure
```
integrated_monitor/
├── main.py                 # FastAPI application
├── models.py              # Pydantic models
├── database.py            # Database configuration
├── prometheus_metrics.py  # Metrics exporter
├── services/              # Business logic services
│   ├── heartbeat_monitor.py
│   ├── s3_monitor.py
│   ├── s3_api_monitor.py
│   ├── manual_test.py
│   └── grafana_service.py
├── templates/             # HTML templates
├── static/               # Static assets
├── grafana/              # Grafana configuration
├── docker-compose.yml    # Docker services
└── requirements.txt      # Python dependencies
```

### Development Setup

1. **Install Development Dependencies**
   ```bash
   pip install -r requirements.txt
   pip install pytest black flake8
   ```

2. **Run Tests**
   ```bash
   pytest tests/
   ```

3. **Code Formatting**
   ```bash
   black .
   flake8 .
   ```

4. **Start Development Server**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

### Adding New Features

1. **Create Service Class**
   ```python
   # services/new_service.py
   class NewService:
       async def add_config(self, config):
           # Implementation
           pass
   ```

2. **Add Pydantic Models**
   ```python
   # models.py
   class NewConfigCreate(BaseModel):
       name: str
       # Other fields
   ```

3. **Add API Endpoints**
   ```python
   # main.py
   @app.post("/api/new/add")
   async def add_new_config(config: NewConfigCreate):
       return await new_service.add_config(config)
   ```

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

### Code Standards
- Follow PEP 8 style guidelines
- Add type hints to all functions
- Include docstrings for all classes and methods
- Write tests for new features

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## 🆘 Support

For support and questions:
- Create an issue on GitHub
- Check the API documentation
- Review the logs for troubleshooting

---

## 🔄 Changelog

### Version 1.0.0
- Initial release
- Complete API monitoring system
- Grafana dashboard integration
- Docker deployment support
- Comprehensive documentation
