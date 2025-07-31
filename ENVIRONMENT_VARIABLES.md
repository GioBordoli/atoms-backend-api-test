# Environment Variables Configuration

This document lists all the environment variables required for the Requirements Analysis API to function properly.

## Required Environment Variables

### 1. GEMINI_API_KEY
- **Purpose**: API key for Google Gemini 2.0 Flash AI model
- **Type**: String
- **Example**: `AIzaSyDhJ1K8X9Y2Z3A4B5C6D7E8F9G01I2J3K4L5M6N7O8P9`
- **How to get**: 
  1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
  2. Create a new API key
  3. Copy the key and set it as the environment variable

### 2. GOOGLE_APPLICATION_CREDENTIALS (Recommended)
- **Purpose**: Path to Google Cloud service account JSON key file for authentication
- **Type**: String (File Path)
- **Example**: `/path/to/service-account-key.json`
- **How to get**:
  1. Create a service account in Google Cloud Console
  2. Download the JSON key file
  3. Set the file path as the environment variable

### 3. GOOGLE_SERVICE_ACCOUNT_KEY (Alternative)
- **Purpose**: Base64-encoded service account JSON key content
- **Type**: String (JSON)
- **Example**: `eyJ0eXBlIjoic2VydmljZV9hY2NvdW50IiwicHJvamVjdF9pZCI6InJlcXVpcmVtZW50LXJlZmluZXItNDYyNzIyIi...`
- **How to get**: Base64 encode your service account JSON key file

### 4. PORT (Optional)
- **Purpose**: Port number for the FastAPI application
- **Type**: Integer
- **Default**: 8080
- **Example**: `8080`
- **Note**: Google Cloud Run uses PORT environment variable automatically

## Organization-Based Bucket System

The API uses organization-based buckets instead of a single shared bucket:

- **Bucket Naming**: Each organization gets its own bucket named `{organizationId}-requirements`
- **Auto-Creation**: Buckets are automatically created when the first document is uploaded
- **Permissions**: The service account needs `Storage Object Admin` role to create and manage buckets
- **Location**: Buckets are created in the `US` region by default

## Google Cloud Permissions Required

The service account needs the following permissions:

1. **Storage Object Admin** - To create, read, update, and delete objects in Cloud Storage
2. **Storage Admin** - To create new buckets for organizations
3. **AI Platform User** - To access Google Gemini API (if using service account authentication)

## Google Cloud Environment Variables Setup

When deploying to Google Cloud Run, set these environment variables in the Cloud Console:

1. **Via Console**:
   - Go to Cloud Run > Your Service > Edit & Deploy New Revision
   - Under "Container" section, click "Variables & Secrets"
   - Add each environment variable

2. **Via gcloud CLI**:
   ```bash
   gcloud run deploy requirement-refiner-api \
     --image gcr.io/YOUR_PROJECT_ID/requirement-refiner \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated \
     --set-env-vars GEMINI_API_KEY="your-gemini-key" \
     --set-env-vars GOOGLE_APPLICATION_CREDENTIALS="/etc/secrets/service-account-key.json"
   ```

## Local Development

For local development, create a `.env` file in the project root:

```bash
# .env file (DO NOT COMMIT TO VERSION CONTROL)
GEMINI_API_KEY=your-gemini-api-key-here
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service-account-key.json
PORT=8080
```

## Security Notes

- **Never commit these environment variables to version control**
- **Use Google Cloud Secret Manager for production deployments** (recommended)
- **Rotate API keys regularly**
- **Limit service account permissions to minimum required**

## Verification

After setting up environment variables, you can verify the setup by:

1. **Health Check**: `GET /health`
2. **Test API**: `POST /analyze-requirement` with minimal payload
3. **Check Logs**: Monitor application logs for any missing environment variable errors

## Troubleshooting

### Error: "Missing required environment variables"
- Verify all required variables are set
- Check variable names match exactly (case-sensitive)
- Ensure JSON string is properly formatted (no line breaks)

### Error: "REGULATION_BUCKET_NAME environment variable not set"
- Set the bucket name environment variable
- Verify the bucket exists and is accessible

### Error: "Authentication failed"
- Verify service account JSON is correctly formatted
- Check service account has required permissions
- Ensure the service account key is not expired 