#!/bin/bash

# Simple deployment script for ATOMS Requirements Analysis API
echo "🚀 Deploying ATOMS Requirements Analysis API..."

PROJECT_ID="serious-mile-462615-a2"
SERVICE_NAME="atoms-requirements-api"
REGION="us-central1"
IMAGE_URL="us-central1-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/${SERVICE_NAME}:latest"

# Step 1: Build and push the container
echo "📦 Building and pushing container..."
gcloud builds submit --tag $IMAGE_URL .

# Step 2: Deploy to Cloud Run
echo "🚀 Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE_URL \
  --platform managed \
  --region $REGION \
  --service-account atoms-api-sa@${PROJECT_ID}.iam.gserviceaccount.com \
  --set-env-vars="PROJECT_ID=${PROJECT_ID}" \
  --allow-unauthenticated

echo "✅ Deployment complete!"
echo "🌐 Service URL: https://${SERVICE_NAME}-556525467020.${REGION}.run.app"
echo ""
echo "📚 API Documentation: https://${SERVICE_NAME}-556525467020.${REGION}.run.app/docs"
echo ""
echo "🔑 Note: Your organization has security policies that prevent public access."
echo "   To test the API, use:"
echo "   curl -H \"Authorization: Bearer \$(gcloud auth print-access-token)\" [URL]" 