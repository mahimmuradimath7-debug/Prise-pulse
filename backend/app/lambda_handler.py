"""AWS Lambda Handler for PricePulse.

Enables serverless deployment on AWS Lambda + Amazon API Gateway as specified in the project brief.
Uses Mangum as the ASGI adapter for FastAPI.
"""
from __future__ import annotations

try:
    from mangum import Mangum
    from .main import app
    handler = Mangum(app, lifespan="off")
except ImportError:
    def handler(event, context):
        return {
            "statusCode": 500,
            "body": "Mangum is required for AWS Lambda execution. Install with: pip install mangum",
        }
