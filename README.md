# Dental Clinic Management System

A comprehensive multi-tenant SaaS platform for modern dental practice management. Built with FastAPI, PostgreSQL, and enterprise-grade security.

[![Built by Kwantabit](https://img.shields.io/badge/Built%20by-Kwantabit-blue)](https://kwantabit.com)
[![License: Commercial](https://img.shields.io/badge/License-Commercial-red.svg)](LICENSE)

## 🌟 Features

- **Multi-tenant Architecture**
  - Secure tenant isolation using PostgreSQL Row Level Security (RLS)
  - Tenant-specific configurations and customizations
  - Automatic tenant context management

- **Core Functionalities**
  - Patient Management
  - Appointment Scheduling
  - Treatment Planning
  - Medical Records
  - Billing & Invoicing
  - Prescription Management
  - Reports & Analytics

- **Technical Features**
  - Async FastAPI backend with high performance
  - PostgreSQL with async support
  - Redis caching for optimized performance
  - JWT authentication with refresh tokens
  - Comprehensive API documentation
  - Automated testing suite

## 🚀 Quick Start

### Prerequisites

- Python 3.13+
- PostgreSQL 15+
- Redis (optional)

### Local Development Setup

```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your configurations

# Run database migrations
alembic upgrade head

# Start the development server
uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```

### API Documentation

Once running, access the interactive API documentation:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🏗️ Architecture

```
src/
├── main.py              # Application entrypoint
├── core/               # Core configuration
├── models/             # SQLAlchemy models
├── schemas/            # Pydantic schemas
├── routes/             # API endpoints
├── services/          # Business logic
├── middleware/        # Custom middleware
└── db/                # Database configuration
```

## 🔒 Security

- Row Level Security (RLS) for tenant data isolation
- JWT authentication with refresh tokens
- Encrypted medical records
- Role-based access control
- Request rate limiting
- CORS protection

## 🧪 Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_patients.py -v

# Run with coverage
pytest --cov=src tests/
```

## 📚 Documentation

For detailed documentation, please refer to:
- [API Documentation](docs/api.md)
- [Deployment Guide](docs/deployment.md)
- [Security Overview](docs/security.md)

## ⚖️ License

Copyright © 2025 Kwantabit Technologies. All rights reserved.

This is proprietary software. Unauthorized copying, modification, distribution, or use of this software, via any medium, is strictly prohibited.

## 🏢 About Kwantabit Technologies

[Kwantabit Technologies](https://kwantabit.com) specializes in building enterprise-grade SaaS solutions. Visit our website to learn more about our services and solutions.

## 📞 Support

For support inquiries:
- Email: support@kwantabit.com
- Website: https://kwantabit.com
- Documentation: https://docs.kwantabit.com
