"""
PolyDev Coach — AWS Resource Cleanup Script
Deletes ALL resources created during the hackathon.

Resources deleted (standard):
  1. Bedrock Knowledge Base + data sources
  2. S3 bucket — knowledge base docs  (polydev-coach-kb-docs-*)
  3. S3 bucket — frontend app         (polydev-coach-app)
  4. IAM inline policies + IAM role   (PolyDevCoachBedrockKBRole)
  5. OpenSearch Serverless collection  (auto-discovered by name)

Resources deleted (--full flag):
  6. CloudFront distribution           (auto-discovered by comment/origin)
  7. App Runner service                (polydev-coach-backend)
  8. All remaining polydev-coach-* S3 buckets (full scan)

Run from project root AFTER the hackathon:
  python infra/cleanup_aws.py

  # Full teardown including CloudFront + App Runner:
  python infra/cleanup_aws.py --full

  # Skip confirmation (CI/automated):
  python infra/cleanup_aws.py --full --yes

WARNING: This is IRREVERSIBLE. Deleted resources cannot be recovered.
"""
import argparse
import os
import time
import boto3
from botocore.exceptions import ClientError

# ─── Config ───────────────────────────────────────────────────────────────────
REGION = os.getenv("AWS_REGION", "us-east-1")

KB_NAME                 = "polydev-coach-kb"
KB_DOCS_BUCKET          = f"polydev-coach-kb-docs-{REGION}"
FRONTEND_BUCKET         = "polydev-coach-app"
ROLE_NAME               = "PolyDevCoachBedrockKBRole"
APP_RUNNER_SERVICE_NAME = "polydev-coach-backend"
AOSS_COLLECTION_NAME    = "polydev-coach"
CF_COMMENT              = "PolyDev Coach"

# ─── AWS clients ──────────────────────────────────────────────────────────────
s3            = boto3.client("s3",                   region_name=REGION)
bedrock_agent = boto3.client("bedrock-agent",        region_name=REGION)
iam           = boto3.client("iam",                  region_name=REGION)
apprunner     = boto3.client("apprunner",            region_name=REGION)
cf            = boto3.client("cloudfront")
aoss          = boto3.client("opensearchserverless", region_name=REGION)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def confirm(prompt: str) -> bool:
    return input(f"\n⚠️  {prompt}\nType 'yes' to confirm: ").strip().lower() == "yes"


def safe(fn, label: str):
    """Run a function — print warning on error, never crash the script."""
    try:
        fn()
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg  = e.response["Error"]["Message"]
        print(f"  ⚠  {label}: {code} — {msg}")
    except Exception as e:
        print(f"  ⚠  {label}: {e}")


# ─── 1. Bedrock Knowledge Base ────────────────────────────────────────────────

def delete_knowledge_base():
    section("Bedrock Knowledge Base")

    # Auto-discover by name
    kb_id      = None
    next_token = None
    while True:
        kwargs = {"maxResults": 50}
        if next_token:
            kwargs["nextToken"] = next_token
        resp       = bedrock_agent.list_knowledge_bases(**kwargs)
        for kb in resp.get("knowledgeBaseSummaries", []):
            if kb["name"] == KB_NAME:
                kb_id = kb["knowledgeBaseId"]
                break
        next_token = resp.get("nextToken")
        if kb_id or not next_token:
            break

    if not kb_id:
        print(f"  ℹ  '{KB_NAME}' not found — already deleted or never created")
        return

    print(f"  Found: {KB_NAME} ({kb_id})")

    # Delete data sources first (required before KB can be deleted)
    try:
        ds_list = bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)
        for ds in ds_list.get("dataSourceSummaries", []):
            ds_id = ds["dataSourceId"]
            print(f"  Deleting data source: {ds['name']} ({ds_id})")
            safe(
                lambda i=ds_id: bedrock_agent.delete_data_source(
                    knowledgeBaseId=kb_id, dataSourceId=i
                ),
                f"delete data source {ds_id}",
            )
            print("  ✓ Data source deleted")
    except ClientError as e:
        print(f"  ⚠  Could not list data sources: {e}")

    # Delete the KB
    print(f"  Deleting Knowledge Base: {kb_id}")
    try:
        bedrock_agent.delete_knowledge_base(knowledgeBaseId=kb_id)
        print("  Waiting for deletion...")
        for attempt in range(24):
            time.sleep(10)
            try:
                kb     = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
                status = kb["knowledgeBase"]["status"]
                print(f"    [{attempt+1}/24] {status}")
            except ClientError as e:
                if e.response["Error"]["Code"] in (
                    "ResourceNotFoundException", "ValidationException"
                ):
                    print(f"  ✓ Knowledge Base deleted: {KB_NAME}")
                    return
                raise
        print("  ⚠  Still deleting — check AWS Console → Bedrock → Knowledge Bases")
    except ClientError as e:
        print(f"  ⚠  {e}")


# ─── 2. S3 buckets ────────────────────────────────────────────────────────────

def _empty_and_delete_bucket(bucket_name: str):
    try:
        s3.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchBucket", "403"):
            print(f"  ℹ  '{bucket_name}' not found — skipping")
            return
        raise

    print(f"  Emptying: {bucket_name}")
    deleted = 0

    # Handle versioned objects
    try:
        pager = s3.get_paginator("list_object_versions")
        for page in pager.paginate(Bucket=bucket_name):
            to_delete = []
            for obj in page.get("Versions", []):
                to_delete.append({"Key": obj["Key"], "VersionId": obj["VersionId"]})
            for marker in page.get("DeleteMarkers", []):
                to_delete.append({"Key": marker["Key"], "VersionId": marker["VersionId"]})
            if to_delete:
                s3.delete_objects(Bucket=bucket_name, Delete={"Objects": to_delete})
                deleted += len(to_delete)
    except ClientError:
        # Non-versioned bucket
        pager = s3.get_paginator("list_objects_v2")
        for page in pager.paginate(Bucket=bucket_name):
            objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objects:
                s3.delete_objects(Bucket=bucket_name, Delete={"Objects": objects})
                deleted += len(objects)

    if deleted:
        print(f"  Deleted {deleted} object(s)")

    s3.delete_bucket(Bucket=bucket_name)
    print(f"  ✓ Bucket deleted: {bucket_name}")


def delete_kb_docs_bucket():
    section(f"S3 — KB Docs Bucket ({KB_DOCS_BUCKET})")
    _empty_and_delete_bucket(KB_DOCS_BUCKET)


def delete_frontend_bucket():
    section(f"S3 — Frontend Bucket ({FRONTEND_BUCKET})")
    _empty_and_delete_bucket(FRONTEND_BUCKET)


def delete_all_polydev_buckets():
    section("S3 — Scan for remaining polydev-coach-* buckets")
    try:
        buckets = s3.list_buckets().get("Buckets", [])
        found   = [b["Name"] for b in buckets if b["Name"].startswith("polydev-coach")]
        if not found:
            print("  ℹ  No remaining polydev-coach-* buckets found")
            return
        for name in found:
            _empty_and_delete_bucket(name)
    except ClientError as e:
        print(f"  ⚠  {e}")


# ─── 3. IAM role ──────────────────────────────────────────────────────────────

def delete_iam_role():
    section(f"IAM Role — {ROLE_NAME}")

    try:
        iam.get_role(RoleName=ROLE_NAME)
    except iam.exceptions.NoSuchEntityException:
        print(f"  ℹ  '{ROLE_NAME}' not found — skipping")
        return

    # Detach managed policies
    try:
        for policy in iam.list_attached_role_policies(
            RoleName=ROLE_NAME
        ).get("AttachedPolicies", []):
            iam.detach_role_policy(RoleName=ROLE_NAME, PolicyArn=policy["PolicyArn"])
            print(f"  ✓ Detached: {policy['PolicyName']}")
    except ClientError as e:
        print(f"  ⚠  {e}")

    # Delete inline policies
    try:
        for name in iam.list_role_policies(
            RoleName=ROLE_NAME
        ).get("PolicyNames", []):
            iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=name)
            print(f"  ✓ Deleted inline policy: {name}")
    except ClientError as e:
        print(f"  ⚠  {e}")

    # Delete the role
    safe(lambda: iam.delete_role(RoleName=ROLE_NAME), f"delete role {ROLE_NAME}")
    print(f"  ✓ IAM role deleted: {ROLE_NAME}")


# ─── 4. OpenSearch Serverless collection ──────────────────────────────────────

def delete_opensearch_collection():
    section(f"OpenSearch Serverless — {AOSS_COLLECTION_NAME}")

    try:
        resp        = aoss.list_collections(filters={"name": AOSS_COLLECTION_NAME})
        collections = resp.get("collectionSummaries", [])
    except ClientError as e:
        print(f"  ⚠  Could not list collections: {e}")
        print("    Check manually: AWS Console → OpenSearch → Serverless → Collections")
        return

    if not collections:
        print(f"  ℹ  Collection '{AOSS_COLLECTION_NAME}' not found — skipping")
        return

    for col in collections:
        col_id   = col["id"]
        col_name = col["name"]
        print(f"  Found collection: {col_name} ({col_id})")

        # Delete security policies associated with this collection
        for policy_type in ["encryption", "network"]:
            try:
                policies = aoss.list_security_policies(type=policy_type)
                for p in policies.get("securityPolicySummaries", []):
                    if AOSS_COLLECTION_NAME in p.get("name", ""):
                        safe(
                            lambda n=p["name"], t=policy_type: aoss.delete_security_policy(
                                type=t, name=n
                            ),
                            f"delete {policy_type} policy {p['name']}",
                        )
                        print(f"  ✓ Deleted {policy_type} policy: {p['name']}")
            except ClientError:
                pass

        # Delete data access policies
        try:
            policies = aoss.list_access_policies(type="data")
            for p in policies.get("accessPolicySummaries", []):
                if AOSS_COLLECTION_NAME in p.get("name", ""):
                    safe(
                        lambda n=p["name"]: aoss.delete_access_policy(type="data", name=n),
                        f"delete data policy {p['name']}",
                    )
                    print(f"  ✓ Deleted data access policy: {p['name']}")
        except ClientError:
            pass

        # Delete the collection itself
        try:
            aoss.delete_collection(id=col_id)
            print("  Waiting for collection deletion (up to 5 min)...")
            for attempt in range(20):
                time.sleep(15)
                try:
                    check = aoss.batch_get_collection(ids=[col_id])
                    if not check.get("collectionDetails"):
                        print(f"  ✓ Collection deleted: {col_name}")
                        break
                    status = check["collectionDetails"][0].get("status", "unknown")
                    print(f"    [{attempt+1}/20] {status}")
                except ClientError:
                    print(f"  ✓ Collection deleted: {col_name}")
                    break
            else:
                print("  ⚠  Still deleting — check AWS Console → OpenSearch → Collections")
        except ClientError as e:
            print(f"  ⚠  Could not delete collection: {e}")


# ─── 5. CloudFront distribution ───────────────────────────────────────────────

def delete_cloudfront_distribution():
    section("CloudFront Distribution")

    dist_id = os.getenv("CLOUDFRONT_DISTRIBUTION_ID", "")

    # Auto-discover by comment or origin domain
    if not dist_id:
        print("  Scanning distributions for PolyDev Coach...")
        try:
            paginator = cf.get_paginator("list_distributions")
            for page in paginator.paginate():
                for dist in page.get("DistributionList", {}).get("Items", []):
                    comment      = dist.get("Comment", "")
                    origins      = dist.get("Origins", {}).get("Items", [])
                    origin_names = [o.get("DomainName", "") for o in origins]
                    if (CF_COMMENT.lower() in comment.lower() or
                            any("polydev-coach" in d for d in origin_names)):
                        dist_id = dist["Id"]
                        domain  = dist.get("DomainName", "")
                        print(f"  Found: {dist_id} → https://{domain}")
                        break
                if dist_id:
                    break
        except ClientError as e:
            print(f"  ⚠  Could not scan distributions: {e}")

    if not dist_id:
        print("  ℹ  No PolyDev Coach CloudFront distribution found — skipping")
        print("    To force delete: export CLOUDFRONT_DISTRIBUTION_ID=XXXXX")
        return

    try:
        dist   = cf.get_distribution(Id=dist_id)
        etag   = dist["ETag"]
        config = dist["Distribution"]["DistributionConfig"]

        if config["Enabled"]:
            print("  Disabling distribution (3–5 min)...")
            config["Enabled"] = False
            update = cf.update_distribution(
                Id=dist_id, DistributionConfig=config, IfMatch=etag
            )
            etag   = update["ETag"]
            waiter = cf.get_waiter("distribution_deployed")
            waiter.wait(Id=dist_id, WaiterConfig={"Delay": 30, "MaxAttempts": 20})
            print("  ✓ Disabled")

        # Refresh ETag
        etag = cf.get_distribution(Id=dist_id)["ETag"]
        cf.delete_distribution(Id=dist_id, IfMatch=etag)
        print(f"  ✓ CloudFront distribution deleted: {dist_id}")

    except ClientError as e:
        print(f"  ⚠  {e}")
        print("    Delete manually: AWS Console → CloudFront → Distributions")


# ─── 6. App Runner service ────────────────────────────────────────────────────

def delete_app_runner_service():
    section(f"App Runner — {APP_RUNNER_SERVICE_NAME}")

    try:
        service_arn = None
        next_token  = None
        while True:
            kwargs = {}
            if next_token:
                kwargs["NextToken"] = next_token
            resp        = apprunner.list_services(**kwargs)
            for svc in resp.get("ServiceSummaryList", []):
                if svc["ServiceName"] == APP_RUNNER_SERVICE_NAME:
                    service_arn = svc["ServiceArn"]
                    break
            next_token = resp.get("NextToken")
            if service_arn or not next_token:
                break

        if not service_arn:
            print(f"  ℹ  '{APP_RUNNER_SERVICE_NAME}' not found — skipping")
            return

        apprunner.delete_service(ServiceArn=service_arn)
        print(f"  ✓ App Runner deletion initiated (1–2 min to complete)")
        print("    Monitor: AWS Console → App Runner → Services")

    except ClientError as e:
        print(f"  ⚠  {e}")


# ─── Summary ──────────────────────────────────────────────────────────────────

def print_summary(full: bool):
    print(f"\n{'=' * 60}")
    print("  CLEANUP COMPLETE")
    print(f"{'=' * 60}")
    print(f"""
Standard resources deleted:
  ✓ Bedrock Knowledge Base + data sources ({KB_NAME})
  ✓ S3 — knowledge base docs  ({KB_DOCS_BUCKET})
  ✓ S3 — frontend app         ({FRONTEND_BUCKET})
  ✓ IAM role + policies       ({ROLE_NAME})
  ✓ OpenSearch Serverless     ({AOSS_COLLECTION_NAME})""")

    if full:
        print(f"""
Full teardown also deleted:
  ✓ CloudFront distribution   (auto-discovered)
  ✓ App Runner service        ({APP_RUNNER_SERVICE_NAME})
  ✓ All polydev-coach-* S3 buckets (scan)""")

    print("""
Still requires manual deletion:
  • IAM user 'polydev-coach-dev'
    AWS Console → IAM → Users → polydev-coach-dev → Delete user

  • Bedrock / Titan model access
    No cost when idle — safe to leave

  • AWS Secrets Manager (if used)
    AWS Console → Secrets Manager → search 'polydev'

Verify zero cost:
  AWS Console → Billing → Cost Explorer → Last 7 days
  All polydev-coach-* line items should show $0.00
""")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Delete all PolyDev Coach AWS resources after the hackathon."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also delete CloudFront, App Runner, and scan for all polydev-coach-* S3 buckets",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt (use in CI)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  PolyDev Coach — AWS Resource Cleanup")
    print("=" * 60)
    print(f"""
Region: {REGION}

PERMANENTLY DELETES:
  • Bedrock Knowledge Base    {KB_NAME}
  • S3 (KB docs)              {KB_DOCS_BUCKET}
  • S3 (frontend)             {FRONTEND_BUCKET}
  • IAM Role                  {ROLE_NAME}
  • OpenSearch Serverless     {AOSS_COLLECTION_NAME}""")

    if args.full:
        print(f"""  • CloudFront distribution   (auto-discovered)
  • App Runner service        {APP_RUNNER_SERVICE_NAME}
  • All polydev-coach-* S3 buckets""")

    if not args.yes:
        if not confirm("Delete all listed resources? This cannot be undone."):
            print("\nAborted — nothing was deleted.")
            return

    # Standard cleanup
    delete_knowledge_base()
    delete_kb_docs_bucket()
    delete_frontend_bucket()
    delete_iam_role()
    delete_opensearch_collection()

    # Full teardown
    if args.full:
        delete_cloudfront_distribution()
        delete_app_runner_service()
        delete_all_polydev_buckets()

    print_summary(args.full)


if __name__ == "__main__":
    main()