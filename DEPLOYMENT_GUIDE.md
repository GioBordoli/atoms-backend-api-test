# Requirements Analysis API - Deployment Guide

This guide walks you through deploying the Requirements Analysis API to Google Cloud Run.

## Prerequisites

1. **Google Cloud Project**: Active GCP project with billing enabled
2. **Google Cloud CLI**: Installed and authenticated
3. **Docker**: Installed (for local testing)
4. **APIs Enabled**:
   - Cloud Run API
   - Cloud Build API
   - Container Registry API
   - Cloud Storage API

## Step 1: Enable Required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  containerregistry.googleapis.com \
  storage.googleapis.com
```

## Step 2: Set Up Service Account

1. **Create Service Account**:
   ```bash
   gcloud iam service-accounts create requirement-refiner-sa \
     --display-name="Requirements Refiner Service Account"
   ```

2. **Grant Required Permissions**:
   ```bash
   # For Cloud Storage access
   gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
     --member="serviceAccount:requirement-refiner-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
     --role="roles/storage.objectViewer"
   

   ```

3. **Generate Service Account Key**:
   ```bash
   gcloud iam service-accounts keys create service-account-key.json \
     --iam-account=requirement-refiner-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com
   ```

## Step 3: Set Up Cloud Storage Bucket

1. **Create Bucket for Regulation Documents**:
   ```bash
   gsutil mb gs://YOUR_REGULATIONS_BUCKET_NAME
   ```

2. **Upload Regulation PDFs**:
   ```bash
   gsutil cp your-regulation-document.pdf gs://YOUR_REGULATIONS_BUCKET_NAME/
   ```



## Step 4: Get Gemini API Key

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key
3. Copy the API key value

## Step 5: Configure Environment Variables

Create environment variables for deployment:

```bash
# Set your project ID
export PROJECT_ID=your-gcp-project-id

# Set environment variables
export GEMINI_API_KEY="your-gemini-api-key"
export REGULATION_BUCKET_NAME="your-regulations-bucket"
export GOOGLE_SERVICE_ACCOUNT_KEY='{"type":"service_account","project_id":"your-project",...}'
```

## Step 6: Deploy to Cloud Run

### Option A: Using Cloud Build (Recommended)

1. **Submit Build**:
   ```bash
   gcloud builds submit --config cloudbuild.yaml .
   ```

2. **Set Environment Variables**:
   ```bash
   gcloud run services update requirement-refiner-api \
     --region=us-central1 \
     --set-env-vars GEMINI_API_KEY="$GEMINI_API_KEY" \
     --set-env-vars REGULATION_BUCKET_NAME="$REGULATION_BUCKET_NAME" \
     --set-env-vars GOOGLE_SERVICE_ACCOUNT_KEY="$GOOGLE_SERVICE_ACCOUNT_KEY"
   ```

### Option B: Manual Docker Deployment

1. **Build and Push Container**:
   ```bash
   # Build image
   docker build -t gcr.io/$PROJECT_ID/requirement-refiner .
   
   # Push to Container Registry
   docker push gcr.io/$PROJECT_ID/requirement-refiner
   ```

2. **Deploy to Cloud Run**:
   ```bash
   gcloud run deploy requirement-refiner-api \
     --image gcr.io/$PROJECT_ID/requirement-refiner \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated \
     --memory 2Gi \
     --cpu 2 \
     --timeout 300 \
     --max-instances 10 \
     --set-env-vars GEMINI_API_KEY="$GEMINI_API_KEY" \
     --set-env-vars REGULATION_BUCKET_NAME="$REGULATION_BUCKET_NAME" \
     --set-env-vars GOOGLE_SERVICE_ACCOUNT_KEY="$GOOGLE_SERVICE_ACCOUNT_KEY"
   ```

## Step 7: Test the Deployment

1. **Get Service URL**:
   ```bash
   gcloud run services describe requirement-refiner-api \
     --region=us-central1 \
     --format="value(status.url)"
   ```

2. **Health Check**:
   ```bash
   curl https://YOUR_CLOUD_RUN_URL/health
   ```

3. **Test API**:
   ```bash
   curl -X POST https://YOUR_CLOUD_RUN_URL/analyze-requirement \
     -H "Content-Type: application/json" \
     -d '{
       "original_requirement": "The system shall respond within 2 seconds",
       "regulation_document_name": "your-regulation-document.pdf",
       "system_name": "Test System",
       "objective": "Performance testing",
       "temperature": 0.1
     }'
   ```

## Step 8: Monitor and Logs

1. **View Logs**:
   ```bash
   gcloud logs read "resource.type=cloud_run_revision" --limit=50
   ```

2. **Monitor Performance**:
   - Go to [Cloud Run Console](https://console.cloud.google.com/run)
   - Click on your service
   - View metrics and logs

## Security Best Practices

1. **Use Secret Manager** (Production):
   ```bash
   # Store secrets in Secret Manager
   echo -n "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=-
   echo -n "$GOOGLE_SERVICE_ACCOUNT_KEY" | gcloud secrets create service-account-key --data-file=-
   ```

2. **Update Cloud Run to use secrets**:
   ```bash
   gcloud run services update requirement-refiner-api \
     --region=us-central1 \
     --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
     --set-secrets GOOGLE_SERVICE_ACCOUNT_KEY=service-account-key:latest
   ```

## Troubleshooting

### Common Issues

1. **"Permission denied" errors**:
   - Verify service account has correct roles
   - Check if APIs are enabled

2. **"File not found" for regulation documents**:
   - Verify bucket name and file names
   - Check Cloud Storage permissions

3. **"Invalid API key" for Gemini**:
   - Verify API key is correct
   - Check if Gemini API is enabled in your project

### Debugging

1. **Check logs**:
   ```bash
   gcloud logs tail "resource.type=cloud_run_revision AND resource.labels.service_name=requirement-refiner-api"
   ```

2. **Test locally**:
   ```bash
   # Set environment variables
   export GEMINI_API_KEY="your-key"
   export GOOGLE_SERVICE_ACCOUNT_KEY="your-json"
   export REGULATION_BUCKET_NAME="your-bucket"
   
   # Run locally
   python app.py
   ```

## Cost Optimization

1. **Set minimum instances to 0** for cost savings
2. **Use appropriate memory/CPU allocation**
3. **Monitor usage** via Cloud Monitoring
4. **Set up billing alerts**

## Maintenance

1. **Regular updates**: Keep dependencies updated
2. **Monitor performance**: Set up alerts for errors/latency

4. **Security updates**: Rotate API keys and service account keys regularly

## Support

For issues with deployment:
1. Check the logs for error messages
2. Verify all environment variables are set
3. Test individual components (Gemini API, Cloud Storage)
4. Review the troubleshooting section above 