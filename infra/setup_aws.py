"""
PolyDev Coach — AWS Infrastructure Setup Script
Automates creation of:
  1. S3 bucket for knowledge base documents
  2. Upload of all 3 markdown files
  3. Bedrock Knowledge Base (Bedrock-managed vector store)
  4. S3 data source + sync

Run once from the project root before deploying the app:
  python infra/setup_aws.py

Requirements:
  pip install boto3
  AWS credentials with bedrock:*, s3:*, iam:* permissions

NOTE: Uses Bedrock's built-in managed vector store (no OpenSearch
      Serverless setup required). This is the simplest approach and
      fully supported by Amazon Bedrock Knowledge Bases.
"""
import json
import os
import time
import boto3
from botocore.exceptions import ClientError

# ─── Config ───────────────────────────────────────────────────────────────────
REGION      = os.getenv("AWS_REGION", "us-east-1")
KB_NAME     = "polydev-coach-kb"
BUCKET_NAME = f"polydev-coach-kb-docs-{REGION}"
ROLE_NAME   = "PolyDevCoachBedrockKBRole"
ACCOUNT_ID  = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]

# Titan embedding model — required for Bedrock-managed vector store
# (Nova models are not used for embeddings; Titan V2 is the correct choice)
EMBEDDING_MODEL_ARN = (
    f"arn:aws:bedrock:{REGION}::foundation-model/"
    "amazon.titan-embed-text-v2:0"
)

# Knowledge base documents — paths relative to project root
KB_DOCS = [
    "knowledge-base/mulesoft-best-practices.md",
    "knowledge-base/python-enterprise-patterns.md",
    "knowledge-base/java-clean-code.md",
]

# ─── AWS clients ──────────────────────────────────────────────────────────────
s3            = boto3.client("s3",            region_name=REGION)
bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)
iam           = boto3.client("iam",           region_name=REGION)


def create_s3_bucket():
    print(f"Creating S3 bucket: {BUCKET_NAME}")
    try:
        if REGION == "us-east-1":
            s3.create_bucket(Bucket=BUCKET_NAME)
        else:
            s3.create_bucket(
                Bucket=BUCKET_NAME,
                CreateBucketConfiguration={"LocationConstraint": REGION},
            )
        s3.put_public_access_block(
            Bucket=BUCKET_NAME,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        print(f"  ✓ Bucket created: {BUCKET_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "BucketAlreadyOwnedByYou":
            print(f"  ✓ Bucket already exists: {BUCKET_NAME}")
        else:
            raise


def upload_kb_docs():
    print("Uploading knowledge base documents to S3...")
    for doc_path in KB_DOCS:
        if not os.path.exists(doc_path):
            print(f"  ⚠ Skipping {doc_path} — file not found")
            continue
        key = os.path.basename(doc_path)
        s3.upload_file(doc_path, BUCKET_NAME, key)
        print(f"  ✓ Uploaded: {key}")


def get_or_create_bedrock_role() -> str:
    """
    Create an IAM role that allows Amazon Bedrock to read from S3.
    This role is assumed by the Bedrock Knowledge Base service, not by the app.
    """
    try:
        role = iam.get_role(RoleName=ROLE_NAME)
        print(f"  ✓ Using existing IAM role: {ROLE_NAME}")
        return role["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        pass

    print(f"  Creating IAM role: {ROLE_NAME}")

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": ACCOUNT_ID}
                },
            }
        ],
    }

    role = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description="Allows Amazon Bedrock Knowledge Base to read S3 docs for PolyDev Coach",
    )
    role_arn = role["Role"]["Arn"]

    # Allow Bedrock to read from the S3 bucket
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="S3ReadForKB",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetObject", "s3:ListBucket"],
                    "Resource": [
                        f"arn:aws:s3:::{BUCKET_NAME}",
                        f"arn:aws:s3:::{BUCKET_NAME}/*",
                    ],
                }
            ],
        }),
    )

    # Allow Bedrock to invoke the Titan embedding model
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="BedrockEmbeddingAccess",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["bedrock:InvokeModel"],
                    "Resource": EMBEDDING_MODEL_ARN,
                }
            ],
        }),
    )

    print(f"  ✓ IAM role created: {role_arn}")
    print("  Waiting 15s for IAM propagation...")
    time.sleep(15)
    return role_arn


def create_knowledge_base(role_arn: str) -> str:
    """
    Create a Bedrock Knowledge Base using the Bedrock-managed vector store.

    storageConfiguration is intentionally omitted — when omitted, Bedrock
    automatically provisions and manages its own vector store.
    This avoids the OpenSearch Serverless ValidationException that occurs
    when providing an incomplete storageConfiguration.
    """
    print(f"Creating Bedrock Knowledge Base: {KB_NAME}")

    # Idempotent: return existing KB if already created
    next_token = None
    while True:
        kwargs = {"maxResults": 50}
        if next_token:
            kwargs["nextToken"] = next_token
        response = bedrock_agent.list_knowledge_bases(**kwargs)
        for kb in response.get("knowledgeBaseSummaries", []):
            if kb["name"] == KB_NAME:
                kb_id = kb["knowledgeBaseId"]
                print(f"  ✓ Knowledge Base already exists: {kb_id}")
                return kb_id
        next_token = response.get("nextToken")
        if not next_token:
            break

    # Create KB with Bedrock-managed vector store
    # BEDROCK_MANAGED_VECTOR requires no OpenSearch or external vector DB setup
    response = bedrock_agent.create_knowledge_base(
        name=KB_NAME,
        description=(
            "Best practice documentation for MuleSoft, Python, and Java "
            "used by PolyDev Coach Amazon Nova agents for RAG coaching."
        ),
        roleArn=role_arn,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": EMBEDDING_MODEL_ARN,
            },
        },
        storageConfiguration={
            "type": "BEDROCK_MANAGED_VECTOR",
        },
    )

    kb_id = response["knowledgeBase"]["knowledgeBaseId"]
    print(f"  ✓ Knowledge Base created: {kb_id}")

    # Poll until ACTIVE
    print("  Waiting for Knowledge Base to become ACTIVE (may take 1-2 min)...")
    for attempt in range(40):
        kb     = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
        status = kb["knowledgeBase"]["status"]
        print(f"    [{attempt + 1}/40] status: {status}")
        if status == "ACTIVE":
            print("  ✓ Knowledge Base is ACTIVE")
            break
        if status == "FAILED":
            reasons = kb["knowledgeBase"].get("failureReasons", [])
            raise RuntimeError(f"Knowledge Base FAILED.\nReasons: {reasons}")
        time.sleep(10)
    else:
        raise TimeoutError(
            "Knowledge Base did not become ACTIVE within 400s. "
            "Check AWS Console → Bedrock → Knowledge Bases."
        )

    return kb_id


def create_data_source_and_sync(kb_id: str) -> str:
    """
    Create an S3 data source and trigger document ingestion (chunking + embedding).
    Uses FIXED_SIZE chunking — universally supported without additional config.
    """
    print("Creating S3 data source...")

    # Idempotent: reuse existing data source
    existing = bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)
    for ds in existing.get("dataSourceSummaries", []):
        if ds["name"] == "polydev-coach-s3-docs":
            ds_id = ds["dataSourceId"]
            print(f"  ✓ Data source already exists: {ds_id}")
            return _run_ingestion(kb_id, ds_id)

    ds_response = bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name="polydev-coach-s3-docs",
        description="MuleSoft, Python, Java best-practice markdown files",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{BUCKET_NAME}",
            },
        },
        vectorIngestionConfiguration={
            "chunkingConfiguration": {
                "chunkingStrategy": "FIXED_SIZE",
                "fixedSizeChunkingConfiguration": {
                    "maxTokens": 512,
                    "overlapPercentage": 20,
                },
            }
        },
    )
    ds_id = ds_response["dataSource"]["dataSourceId"]
    print(f"  ✓ Data source created: {ds_id}")
    return _run_ingestion(kb_id, ds_id)


def _run_ingestion(kb_id: str, ds_id: str) -> str:
    """Start an ingestion job and poll until complete."""
    print("  Starting ingestion job (chunking + embedding documents)...")
    sync    = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
    )
    job_id  = sync["ingestionJob"]["ingestionJobId"]
    print(f"  Ingestion job ID: {job_id}")

    for attempt in range(40):
        job    = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id,
            ingestionJobId=job_id,
        )
        status = job["ingestionJob"]["status"]
        stats  = job["ingestionJob"].get("statistics", {})
        print(f"    [{attempt + 1}/40] status: {status} | {stats}")

        if status == "COMPLETE":
            print(f"  ✓ Ingestion complete: {stats}")
            break
        if status == "FAILED":
            reasons = job["ingestionJob"].get("failureReasons", [])
            raise RuntimeError(f"Ingestion FAILED: {reasons}")
        time.sleep(15)
    else:
        raise TimeoutError(
            "Ingestion did not complete within 600s. "
            "Check AWS Console → Bedrock → Knowledge Bases → Data sources."
        )

    return ds_id


def main():
    print("=" * 60)
    print("PolyDev Coach — AWS Infrastructure Setup")
    print("=" * 60)

    create_s3_bucket()
    upload_kb_docs()
    get_or_create_bedrock_role()

    print()
    print("=" * 60)
    print("✅  S3 and IAM setup complete!")
    print()
    print("⚠️  Create the Knowledge Base manually in AWS Console:")
    print("   1. AWS Console → Bedrock → Knowledge Bases → Create")
    print(f"  2. Use S3 source: s3://{BUCKET_NAME}")
    print("   3. Select Titan Text Embeddings V2")
    print("   4. Choose 'Quick create a new vector store'")
    print("   5. Sync the data source")
    print("   6. Copy the KB ID into backend/.env:")
    print("      BEDROCK_KNOWLEDGE_BASE_ID=<your-kb-id>")
    print("=" * 60)

if __name__ == "__main__":
    main()