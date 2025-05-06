# Use a specific version of the official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# --no-cache-dir reduces image size
# --upgrade pip ensures pip is up to date
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the contents of the src directory into the WORKDIR (/app)
COPY src/ .

# Make port 8000 available to the world outside this container (the FastAPI/Uvicorn default)
EXPOSE 8000

# Run main.py when the container launches using uvicorn
# Use 0.0.0.0 to make it accessible from outside the container's network interface
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]