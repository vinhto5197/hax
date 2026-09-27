terraform {
  required_version = ">= 1.10"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.70" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  backend "s3" {
    # The bucket comes from the bootstrap module's output, passed at init:
    # terraform init -backend-config=backend.hcl. Locking is S3-native (a lock
    # object beside the state), so no DynamoDB table is needed.
    key          = "hax/prod.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
