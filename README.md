# UAV Logger with Chatbot Backend

This is an extension of the [UAVLogViewer](https://github.com/ArduPilot/UAVLogViewer) project. It adds a Python-based backend that integrates a chatbot capable of answering questions about MAVLink telemetry data from `.bin` or `.tlog` flight logs.

## Features

- Natural language interface to telemetry data
- Agentic chatbot behavior (maintains conversation context)
- Anomaly detection and reasoning
- LLM support (Gemini)

## Prerequisites

- Git
- Docker and Docker Compose

## Build Setup

# Docker
```bash
git clone https://github.com/miguelloeza210/UAVLogViewer.git
git submodule update --init --recursive
cd UAVLogViewer

# Create a .env file in the root directory of the UAVLogViewer project 
# and add your API key and configuration.
# (the same directory where docker-compose.yml is located)
echo "GEMINI_MODEL_NAME=gemini-1.5-flash" >> .env
echo "GEMINI_API_KEY=<YOUR_ACTUAL_GEMINI_API_KEY>" >> .env
echo "VUE_APP_API_URL=http://backend:8000" >> .env

# Build Docker Image
docker-compose up --build
```
Navigate to [localhost:8080](localhost:8080) in your web browser