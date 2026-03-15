"""
PolyDev Coach — AWS Resource Cleanup Script
Deletes ALL resources created by infra/setup_aws.py after the hackathon.

Resources deleted:
  1. Bedrock Knowledge Base data source (ingestion jobs)
  2. Bedrock Knowledge Base
  3. S3 bucket contents + bucket
  4. IAM inline policies + IAM role
  5. (Optional) App Runner service
  6. (Optional) CloudFront distribution + S3 frontend bucket

Run from project root AFTER the hackathon:
  python infra/cleanup_aws.py

  # To also delete App Runner + CloudFront (full teardown):
  python infra/cleanup_aws.py --full

WARNING: This is IRREVERSIBLE. All indexed documents, knowledge base
         vectors, and uploaded files will be permanently deleted.
"""
import argparse
import os
import time
import boto3
from botocore.exceptions import ClientError

# ─── Config — must match setup_aws.py ────────────────────────────────────────
REGION      = os.getenv("AWS_REGION", "us-east-1")
KB_NAME     = "polydev-coach-kb"
BUCKET_NAME = f"polydev-coach-kb-docs-{REGION}"
ROLE_NAME   = "PolyDevCoachBedrockKBRole"

# Optional — only used with --full flag
APP_RUNNER_SERVICE_NAME  = "polydev-coach-backend"
FRONTEND_BUCKET_NAME     = os.getenv("FRONTEND_S3_BUCKET", "polydev-coach-frontend")
CLOUDFRONT_DIST_ID       = os.getenv("CLOUDFRONT_DISTRIBUTION_ID", "")

# ─── AWS clients ──────────────────────────────────────────────────────────────
s3            = boto3.client("s3",            region_name=REGION)
bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)
iam           = boto3.client("iam",           region_name=REGION)
apprunner     = boto3.client("apprunner",     region_name=REGION)
cloudfront    = boto3.client("cloudfront")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def confirm(message: str) -> bool:
    """Ask user to confirm before destructive action."""
    answer = input(f"\n⚠️  {message}\nType 'yes' to confirm: ").strip().lower()
    return answer == "yes"


def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ─── Step 1: Bedrock Knowledge Base ──────────────────────────────────────────

def delete_knowledge_base():
    section("Deleting Bedrock Knowledge Base")

    # Find KB by name
    kb_id = None
    next_token = None
    while True:
        kwargs = {"maxResults": 50}
        if next_token:
            kwargs["nextToken"] = next_token
        response = bedrock_agent.list_knowledge_bases(**kwargs)
        for kb in response.get("knowledgeBaseSummaries", []):
            if kb["name"] == KB_NAME:
                kb_id = kb["knowledgeBaseId"]
                break
        next_token = response.get("nextToken")
        if kb_id or not next_token:
            break

    if not kb_id:
        print(f"  ℹ Knowledge Base '{KB_NAME}' not found — already deleted or never created")
        return

    print(f"  Found Knowledge Base: {kb_id}")

    # Delete all data sources first
    try:
        ds_response = bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)
        for ds in ds_response.get("dataSourceSummaries", []):
            ds_id   = ds["dataSourceId"]
            ds_name = ds["name"]
            print(f"  Deleting data source: {ds_name} ({ds_id})")
            bedrock_agent.delete_data_source(
                knowledgeBaseId=kb_id,
                dataSourceId=ds_id,
            )
            print(f"  ✓ Data source deleted: {ds_name}")
    except ClientError as e:
        print(f"  ⚠ Could not list/delete data sources: {e}")

    # Delete the Knowledge Base
    print(f"  Deleting Knowledge Base: {KB_NAME} ({kb_id})")
    try:
        bedrock_agent.delete_knowledge_base(knowledgeBaseId=kb_id)
        # Poll until gone
        for attempt in range(20):
            time.sleep(10)
            try:
                kb     = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
                status = kb["knowledgeBase"]["status"]
                print(f"    [{attempt + 1}/20] status: {status}")
                if status == "DELETING":
                    continue
            except ClientError as e:
                if e.response["Error"]["Code"] in ("ResourceNotFoundException", "ValidationException"):
                    print(f"  ✓ Knowledge Base deleted: {KB_NAME}")
                    break
                raise
        else:
            print("  ⚠ Knowledge Base deletion still in progress — check AWS Console")
    except ClientError as e:
        print(f"  ⚠ Could not delete Knowledge Base: {e}")


# ─── Step 2: S3 knowledge base bucket ────────────────────────────────────────

def delete_s3_bucket(bucket_name: str, label: str = ""):
    section(f"Deleting S3 Bucket: {bucket_name} {label}")

    # Check bucket exists
    try:
        s3.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            print(f"  ℹ Bucket '{bucket_name}' not found — already deleted")
            return
        raise

    # Delete all object versions (handles versioning-enabled buckets)
    print(f"  Emptying bucket: {bucket_name}")
    try:
        paginator = s3.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket_name):
            objects_to_delete = []

            for obj in page.get("Versions", []):
                objects_to_delete.append(
                    {"Key": obj["Key"], "VersionId": obj["VersionId"]}
                )
            for marker in page.get("DeleteMarkers", []):
                objects_to_delete.append(
                    {"Key": marker["Key"], "VersionId": marker["VersionId"]}
                )

            if objects_to_delete:
                s3.delete_objects(
                    Bucket=bucket_name,
                    Delete={"Objects": objects_to_delete},
                )
                print(f"    Deleted {len(objects_to_delete)} object version(s)")
    except ClientError:
        # Bucket may not have versioning — try regular delete
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                s3.delete_objects(
                    Bucket=bucket_name,
                    Delete={"Objects": objects},
                )
                print(f"    Deleted {len(objects)} object(s)")

    # Delete the bucket itself
    s3.delete_bucket(Bucket=bucket_name)
    print(f"  ✓ Bucket deleted: {bucket_name}")


# ─── Step 3: IAM role ─────────────────────────────────────────────────────────

def delete_iam_role():
    section(f"Deleting IAM Role: {ROLE_NAME}")

    # Check role exists
    try:
        iam.get_role(RoleName=ROLE_NAME)
    except iam.exceptions.NoSuchEntityException:
        print(f"  ℹ IAM role '{ROLE_NAME}' not found — already deleted")
        return

    # Detach all managed policies
    try:
        attached = iam.list_attached_role_policies(RoleName=ROLE_NAME)
        for policy in attached.get("AttachedPolicies", []):
            iam.detach_role_policy(
                RoleName=ROLE_NAME,
                PolicyArn=policy["PolicyArn"],
            )
            print(f"  ✓ Detached managed policy: {policy['PolicyName']}")
    except ClientError as e:
        print(f"  ⚠ Could not detach managed policies: {e}")

    # Delete all inline policies
    try:
        inline = iam.list_role_policies(RoleName=ROLE_NAME)
        for policy_name in inline.get("PolicyNames", []):
            iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=policy_name)
            print(f"  ✓ Deleted inline policy: {policy_name}")
    except ClientError as e:
        print(f"  ⚠ Could not delete inline policies: {e}")

    # Delete the role
    try:
        iam.delete_role(RoleName=ROLE_NAME)
        print(f"  ✓ IAM role deleted: {ROLE_NAME}")
    except ClientError as e:
        print(f"  ⚠ Could not delete IAM role: {e}")


# ─── Step 4 (optional): App Runner ───────────────────────────────────────────

def delete_app_runner_service():
    section(f"Deleting App Runner Service: {APP_RUNNER_SERVICE_NAME}")

    try:
        services = apprunner.list_services()
        service_arn = None
        for svc in services.get("ServiceSummaryList", []):
            if svc["ServiceName"] == APP_RUNNER_SERVICE_NAME:
                service_arn = svc["ServiceArn"]
                break

        if not service_arn:
            print(f"  ℹ App Runner service '{APP_RUNNER_SERVICE_NAME}' not found")
            return

        print(f"  Found service: {service_arn}")
        apprunner.delete_service(ServiceArn=service_arn)
        print(f"  ✓ App Runner service deletion initiated: {APP_RUNNER_SERVICE_NAME}")
        print("    (Takes 1-2 min to fully delete — check AWS Console)")

    except ClientError as e:
        print(f"  ⚠ Could not delete App Runner service: {e}")


# ─── Step 5 (optional): CloudFront + frontend S3 ─────────────────────────────

def delete_cloudfront_distribution():
    section("Deleting CloudFront Distribution")

    if not CLOUDFRONT_DIST_ID:
        print("  ℹ CLOUDFRONT_DISTRIBUTION_ID not set — skipping")
        print("    Set env var or delete manually in AWS Console → CloudFront")
        return

    try:
        # Get current config to retrieve ETag (required for delete)
        dist = cloudfront.get_distribution(Id=CLOUDFRONT_DIST_ID)
        etag = dist["ETag"]
        config = dist["Distribution"]["DistributionConfig"]

        # Must disable before deleting
        if config["Enabled"]:
            print(f"  Disabling distribution: {CLOUDFRONT_DIST_ID}")
            config["Enabled"] = False
            update = cloudfront.update_distribution(
                Id=CLOUDFRONT_DIST_ID,
                DistributionConfig=config,
                IfMatch=etag,
            )
            etag = update["ETag"]
            print("  Waiting for distribution to deploy as disabled (2-5 min)...")
            waiter = cloudfront.get_waiter("distribution_deployed")
            waiter.wait(Id=CLOUDFRONT_DIST_ID)

        # Get fresh ETag after disable
        dist = cloudfront.get_distribution(Id=CLOUDFRONT_DIST_ID)
        etag = dist["ETag"]

        cloudfront.delete_distribution(Id=CLOUDFRONT_DIST_ID, IfMatch=etag)
        print(f"  ✓ CloudFront distribution deleted: {CLOUDFRONT_DIST_ID}")

    except ClientError as e:
        print(f"  ⚠ Could not delete CloudFront distribution: {e}")
        print("    Delete manually: AWS Console → CloudFront → Distributions")


# ─── Summary ──────────────────────────────────────────────────────────────────

def print_summary(full: bool):
    print(f"\n{'=' * 60}")
    print("  CLEANUP COMPLETE")
    print(f"{'=' * 60}")
    print("""
Resources deleted:
  ✓ Bedrock Knowledge Base + data sources
  ✓ S3 bucket (knowledge base docs)
  ✓ IAM role + policies (PolyDevCoachBedrockKBRole)""")

    if full:
        print("""  ✓ App Runner backend service
  ✓ CloudFront distribution
  ✓ S3 frontend bucket""")

    print("""
Resources NOT deleted by this script (delete manually if needed):
  • IAM user: polydev-coach-dev
    → AWS Console → IAM → Users → polydev-coach-dev → Delete
  • Bedrock model access (no cost when not in use — safe to leave)
  • Amazon Titan Embed V2 model access (no cost when not in use)

To verify nothing is left running:
  AWS Console → Bedrock → Knowledge Bases  (should be empty)
  AWS Console → S3                          (polydev-coach-* buckets gone)
  AWS Console → IAM → Roles                (PolyDevCoachBedrockKBRole gone)
  AWS Console → Cost Explorer              (verify $0 going forward)
""")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Delete all PolyDev Coach AWS resources after the hackathon."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also delete App Runner service, CloudFront distribution, and frontend S3 bucket",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt (use in CI/automated cleanup)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  PolyDev Coach — AWS Resource Cleanup")
    print("=" * 60)
    print(f"""
This will PERMANENTLY DELETE:
  • Bedrock Knowledge Base: {KB_NAME}
  • S3 Bucket:              {BUCKET_NAME}
  • IAM Role:               {ROLE_NAME}""")

    if args.full:
        print(f"""  • App Runner Service:     {APP_RUNNER_SERVICE_NAME}
  • Frontend S3 Bucket:     {FRONTEND_BUCKET_NAME}
  • CloudFront Distribution: {CLOUDFRONT_DIST_ID or '(from env var)'}""")

    if not args.yes:
        if not confirm("Are you sure you want to delete all these resources?"):
            print("\nAborted. No resources were deleted.")
            return

    # Core cleanup (always runs)
    delete_knowledge_base()
    delete_s3_bucket(BUCKET_NAME, "(knowledge base docs)")
    delete_iam_role()

    # Optional full teardown
    if args.full:
        delete_app_runner_service()
        delete_cloudfront_distribution()
        delete_s3_bucket(FRONTEND_BUCKET_NAME, "(frontend)")

    print_summary(args.full)


if __name__ == "__main__":
    main()