# Without this, Terraform infers `hashicorp/oci` for the `oci_` resources in
# this module — a different, unconfigured provider that fails every call with
# 401 NotAuthenticated. A child module must declare the providers it uses.
terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
}
