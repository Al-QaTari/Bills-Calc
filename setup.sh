#!/bin/bash

# Setup script for Streamlit Cloud deployment
# This script ensures all dependencies are properly installed

echo "🔧 Setting up Treasury Bills Calculator..."

# Install Playwright browsers
echo "📦 Installing Playwright browsers..."
playwright install --with-deps chromium

# Verify installation
echo "✅ Playwright browsers installed successfully"

# Set environment variables for better performance
export PYTHONPATH="${PYTHONPATH}:${PWD}"

echo "🚀 Setup completed successfully!"
