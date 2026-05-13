import boto3
import os
from typing import BinaryIO


class S3Service:
    def __init__(self):
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION"),
        )
        self.bucket_name = os.getenv("S3_BUCKET_NAME")
        self.kms_key_id = os.getenv("KMS_KEY_ID")

    def upload_pdf(self, file_obj: BinaryIO, doc_id: str) -> str:
        """Upload PDF to S3 with SSE-KMS encryption. Returns s3:// URI."""
        key = f"documents/{doc_id}.pdf"
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=file_obj.read(),
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=self.kms_key_id,
            Metadata={"doc_id": doc_id},
        )
        return f"s3://{self.bucket_name}/{key}"

    def download_pdf(self, doc_id: str) -> bytes:
        key = f"documents/{doc_id}.pdf"
        response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
        return response["Body"].read()

    def delete_pdf(self, doc_id: str) -> None:
        key = f"documents/{doc_id}.pdf"
        self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
