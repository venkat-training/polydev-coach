"""
PolyDev Coach — AWS Infrastructure Setup Script
Automates creation of:
  1. S3 bucket for knowledge base documents
  2. Upload of all 3 markdown files
  3. Bedrock Knowledge Base with Nova Lite embeddings
  4. Data source sync

Run once before deploying the app:
  python infra/setup_aws.py

Requirements:
  pip install boto3
  AWS credentials with bedrock:* and s3:* permissions
"""
import json
import os
import time
import boto3

REGION = os.getenv("AWS_REGION", "us-east-1")
KB_NAME = "polydev-coach-kb"
BUCKET_NAME = f"polydev-coach-kb-docs-{REGION}"

# Knowledge base documents (relative to project root)
KB_DOCS = [
    "knowledge-base/mulesoft-best-practices.md",
    "knowledge-base/python-enterprise-patterns.md",
    "knowledge-base/java-clean-code.md",
]

s3 = boto3.client("s3", region_name=REGION)
bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)


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
        # Block public access
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
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"  ✓ Bucket already exists: {BUCKET_NAME}")


def upload_kb_docs():
    print("Uploading knowledge base documents to S3...")
    for doc_path in KB_DOCS:
        key = os.path.basename(doc_path)
        s3.upload_file(doc_path, BUCKET_NAME, key)
        print(f"  ✓ Uploaded: {key}")


def get_or_create_bedrock_role():
    """Create an IAM role for Bedrock Knowledge Base to access S3."""
    role_name = "PolyDevCoachBedrockKBRole"
    try:
        role = iam.get_role(RoleName=role_name)
        print(f"  ✓ Using existing IAM role: {role_name}")
        return role["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        pass

    print(f"  Creating IAM role: {role_name}")
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }
    role = iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description="Bedrock Knowledge Base role for PolyDev Coach",
    )
    role_arn = role["Role"]["Arn"]

    # Attach S3 read policy
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="S3ReadForKB",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:ListBucket"],
                "Resource": [
                    f"arn:aws:s3:::{BUCKET_NAME}",
                    f"arn:aws:s3:::{BUCKET_NAME}/*",
                ],
            }],
        }),
    )
    # Attach Bedrock model access
    iam.attach_role_policy(
        RoleName=role_name,
        PolicyArn="arn:aws:iam::aws:policy/AmazonBedrockFullAccess",
    )
    print(f"  ✓ IAM role created: {role_arn}")
    time.sleep(10)  # Wait for IAM propagation
    return role_arn


def create_knowledge_base(role_arn: str) -> str:
    print(f"Creating Bedrock Knowledge Base: {KB_NAME}")

    # Check if already exists
    existing = bedrock_agent.list_knowledge_bases(maxResults=20)
    for kb in existing.get("knowledgeBaseSummaries", []):
        if kb["name"] == KB_NAME:
            kb_id = kb["knowledgeBaseId"]
            print(f"  ✓ Knowledge Base already exists: {kb_id}")
            return kb_id

    response = bedrock_agent.create_knowledge_base(
        name=KB_NAME,
        description="Best practice docs for MuleSoft, Python, and Java used by PolyDev Coach",
        roleArn=role_arn,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                # Nova Lite embeddings (multimodal, high quality)
                "embeddingModelArn": f"arn:aws:bedrock:{REGION}::foundation-model/amazon.nova-lite-v1:0",
            },
        },
        storageConfiguration={
            "type": "OPENSEARCH_SERVERLESS",
            # Bedrock auto-creates an OpenSearch Serverless collection
        },
    )
    kb_id = response["knowledgeBase"]["knowledgeBaseId"]
    print(f"  ✓ Knowledge Base created: {kb_id}")

    # Wait for KB to be active
    print("  Waiting for Knowledge Base to become ACTIVE...")
    for _ in range(30):
        kb = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
        status = kb["knowledgeBase"]["status"]
        if status == "ACTIVE":
            break
        if status == "FAILED":
            raise RuntimeError(f"Knowledge Base creation failed: {kb}")
        time.sleep(10)

    return kb_id


def create_data_source_and_sync(kb_id: str):
    print("Creating S3 data source and syncing...")

    ds_response = bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name="polydev-coach-s3-docs",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{BUCKET_NAME}",
            },
        },
        vectorIngestionConfiguration={
            "chunkingConfiguration": {
                "chunkingStrategy": "SEMANTIC",  # Best for markdown docs
            }
        },
    )
    ds_id = ds_response["dataSource"]["dataSourceId"]
    print(f"  ✓ Data source created: {ds_id}")

    # Start sync
    sync = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
    )
    job_id = sync["ingestionJob"]["ingestionJobId"]
    print(f"  Syncing documents (job: {job_id})...")

    for _ in range(30):
        job = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id,
            ingestionJobId=job_id,
        )
        status = job["ingestionJob"]["status"]
        stats = job["ingestionJob"].get("statistics", {})
        if status == "COMPLETE":
            print(f"  ✓ Sync complete: {stats}")
            break
        if status == "FAILED":
            raise RuntimeError(f"Sync failed: {job}")
        time.sleep(10)

    return ds_id


def main():
    print("=" * 60)
    print("PolyDev Coach — AWS Infrastructure Setup")
    print("=" * 60)

    create_s3_bucket()
    upload_kb_docs()
    role_arn = get_or_create_bedrock_role()
    kb_id = create_knowledge_base(role_arn)
    create_data_source_and_sync(kb_id)

    print()
    print("=" * 60)
    print("✅ Setup complete!")
    print(f"   BEDROCK_KNOWLEDGE_BASE_ID={kb_id}")
    print()
    print("Add this to your .env file:")
    print(f"   BEDROCK_KNOWLEDGE_BASE_ID={kb_id}")
    print("=" * 60)


if __name__ == "__main__":
    main()
