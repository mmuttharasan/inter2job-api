"""Vercel serverless entry point — exposes the Flask app as a WSGI handler."""

import sys
import os

# Ensure the project root is on the Python path so `app` package resolves
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app import create_app

app = create_app()
